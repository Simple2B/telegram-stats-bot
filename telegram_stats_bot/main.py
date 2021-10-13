# !/usr/bin/env python
#
# A logging and statistics bot for Telegram based on python-telegram-bot.
# Copyright (C) 2020
# Michael DM Dryden <mk.dryden@utoronto.ca>
#
# This file is part of telegram-stats-bot.
#
# telegram-stats-bot is free software: you can redistribute it and/or modify
# it under the terms of the GNU Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser Public License for more details.
#
# You should have received a copy of the GNU Public License
# along with this program. If not, see [http://www.gnu.org/licenses/].

import logging
import json
import argparse
import shlex
import warnings
import os

import telegram
from telegram.error import BadRequest
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, JobQueue
from telegram.update import Update
import appdirs

from .parse import parse_message
from .log_storage import JSONStore, PostgresStore
from .stats import StatsRunner, get_parser, HelpException
from config import BaseConfig as conf

warnings.filterwarnings("ignore")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

stats = None

try:
    with open("./sticker-keys.json", 'r') as f:
        stickers = json.load(f)
except FileNotFoundError:
    stickers = {}
sticker_idx = None
sticker_id = None


class StatsBot:
    def __init__(self):
        self.updater = Updater(token=conf.BOT_TOKEN, use_context=True)
        self.dispatcher = self.updater.dispatcher

        path = conf.JSON_PATH
        if not os.path.split(path)[0]:  # Empty string for left part of path
            path = os.path.join(appdirs.user_data_dir('telegram-stats-bot'), path)
        os.makedirs(path, exist_ok=True)

        self.bak_store = JSONStore(path)
        self.store = PostgresStore(conf.POSTGRES_URL)
        self.stats = StatsRunner(self.store.engine, tz=conf.TZ)

        # Handlers
        stats_handler = CommandHandler('stats', self.print_stats, filters=~Filters.update.edited_message, run_async=True)
        self.dispatcher.add_handler(stats_handler)

        chat_id_handler = CommandHandler('chatid', self.get_chatid, filters=~Filters.update.edited_message)
        self.dispatcher.add_handler(chat_id_handler)

        if conf.CHAT_ID != 0:
            log_handler = MessageHandler(Filters.chat(chat_id=conf.CHAT_ID), self.log_message)
            self.dispatcher.add_handler(log_handler)


    def log_message(self, update: Update, context: CallbackContext):
        if update.edited_message:
            edited_message, user = parse_message(update.effective_message)
            self.bak_store.append_data('edited-messages', edited_message)
            self.store.update_data('messages', edited_message)
            return

        try:
            logger.info(update.effective_message.message_id)
        except AttributeError:
            logger.warning("No effective_message attribute")
        message, user = parse_message(update.effective_message)

        if message:
            self.bak_store.append_data('messages', message)
            self.store.append_data('messages', message)
        if len(user) > 0:
            for i in user:
                if i:
                    self.bak_store.append_data('user_events', i)
                    self.store.append_data('user_events', i)

    def get_chatid(self, update: Update, context: CallbackContext):
        context.bot.send_message(chat_id=update.effective_chat.id,
                             text=f"Chat id: {update.effective_chat.id}")


    def test_can_read_all_group_messages(self, context: CallbackContext):
        if not context.bot.can_read_all_group_messages:
            logger.error("Bot privacy is set to enabled, cannot log messages!!!")


    def update_usernames_wrapper(self, context: CallbackContext):
        context.dispatcher.run_async(self.update_usernames, context)

    def update_usernames(self, context: CallbackContext):  # context.job.context contains the chat_id
        user_ids = self.stats.get_message_user_ids()
        db_users = self.stats.get_db_users()
        tg_users = {user_id: None for user_id in user_ids}
        to_update = {}
        for u_id in tg_users:
            try:
                user = context.bot.get_chat_member(chat_id=context.job.context, user_id=u_id).user
                tg_users[u_id] = user.name, user.full_name
                if tg_users[u_id] != db_users[u_id]:
                    if tg_users[u_id][1] == db_users[u_id][1]:  # Flag these so we don't insert new row
                        to_update[u_id] = tg_users[u_id][0], None
                    else:
                        to_update[u_id] = tg_users[u_id]
            except KeyError:  # First time user
                to_update[u_id] = tg_users[u_id]
            except BadRequest:  # Handle users no longer in chat or haven't messaged since bot joined
                logger.debug("Couldn't get user %s", u_id)  # debug level because will spam every hour
        self.stats.update_user_ids(to_update)
        if self.stats.users_lock.acquire(timeout=10):
            self.stats.users = self.stats.get_db_users()
            self.stats.users_lock.release()
        else:
            logger.warning("Couldn't acquire username lock.")
            return
        logger.info("Usernames updated")

    def print_stats(self, update: Update, context: CallbackContext):
        if update.effective_user.id not in self.stats.users:
            return

        stats_parser = get_parser(self.stats)
        image = None

        try:
            ns = stats_parser.parse_args(shlex.split(" ".join(context.args)))
        except HelpException as e:
            text = e.msg
            self.send_help(text, context, update)
            return
        except argparse.ArgumentError as e:
            text = str(e)
            self.send_help(text, context, update)
            return
        else:
            args = vars(ns)
            func = args.pop('func')

            try:
                if args['user']:
                    try:
                        uid = args['user']
                        args['user'] = uid, self.stats.users[uid][0]
                    except KeyError:
                        self.send_help("unknown userid", context, update)
                        return
            except KeyError:
                pass

            try:
                if args['me'] and not args['user']:  # Lets auto-user work by ignoring auto-input me arg
                    args['user'] = update.effective_user.id, update.effective_user.name
                del args['me']
            except KeyError:
                pass

            try:
                text, image = func(**args)
            except HelpException as e:
                text = e.msg
                self.send_help(text, context, update)
                return

        if text:
            context.bot.send_message(chat_id=update.effective_chat.id,
                                    text=text,
                                    parse_mode=telegram.ParseMode.MARKDOWN_V2)
        if image:
            context.bot.send_photo(chat_id=update.effective_chat.id, photo=image)

    def send_help(text: str, context: CallbackContext, update: Update):
        """
        Send help text to user. Tries to send a direct message if possible.
        :param text: text to send
        :param context:
        :param update:
        :return:
        """
        try:
            context.bot.send_message(chat_id=update.effective_user.id,
                                    text=f"```\n{text}\n```",
                                    parse_mode=telegram.ParseMode.MARKDOWN_V2)
        except telegram.error.Unauthorized:  # If user has never chatted with bot
            context.bot.send_message(chat_id=update.effective_chat.id,
                                    text=f"```\n{text}\n```",
                                    parse_mode=telegram.ParseMode.MARKDOWN_V2)

    def start_bot(self):
        # TODO review code possition
        job_queue: JobQueue = self.updater.job_queue
        update_users_job = job_queue.run_repeating(self.update_usernames_wrapper, interval=3600, first=5, context=conf.CHAT_ID)
        test_privacy_job = job_queue.run_once(self.test_can_read_all_group_messages, 0)
        # ---

        self.updater.start_polling()
        self.updater.idle()


if __name__ == '__main__':
    bot = StatsBot()

    bot.start_bot()