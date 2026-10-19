"""
send notifications via E-Mail, Telegram and/or WhatsApp
=======================================================

this pure python module depends on the Python Standard Libraries :mod:`email` and :mod:`smtplib`
and the external :mod:`requests` package.
"""
import re

from email.mime.text import MIMEText
from smtplib import SMTP, SMTP_SSL

import requests


__version__ = '0.3.10'


TELEGRAM_MESSAGE_MAX_LEN = 4096         #: maximum length of Telegram notification message body
WHATSAPP_MESSAGE_MAX_LEN = 65536        #: maximum length of WhatsApp notification message body

SMTP_SERVICE_NAME_PORTS = {'smtp': 2_5, 'smtps': 4_6_5, 'smtpTLS': 5_8_7}
""" mapping of SMTP service names to their related IP ports. """
SMTP_PORT_SERVICE_NAMES = {_port: _service_name for _service_name, _port in SMTP_SERVICE_NAME_PORTS.items()}
""" mapping of SMTP port numbers to their related service names. """


def _body_type_conversion(msg_body: str, msg_type: str) -> tuple[str, str]:
    """ convert content of notification message body.

    :param msg_body:            message body string.
    :param msg_type:            message text type to convert to, if it has the 'to_' prefix.
    :return:                    tuple of converted message body and resulting text type (removing the 'to_' prefix).
    """
    if msg_type == 'to_' + 'html':
        msg_body = msg_body.replace('\n', '<br>')
        msg_type = 'html'
    elif msg_type == 'to_' + 'plain':
        msg_body = msg_body.replace('<br>', '\n')
        msg_type = 'plain'
    return msg_body, msg_type


class Notifications:            # pylint: disable=too-many-instance-attributes
    """ send notifications via Email, Telegram or WhatsApp

    specify the sender's credentials on instantiation. a single instance of this class can be used to prepare
    and send all notifications of a server/app.

    the notification channels and the receiver(s) are specified individually for each notification message to send.
    """
    def __init__(self,          # pylint: disable=too-many-arguments,too-many-positional-arguments
                 smtp_server_uri: str = "", mail_from: str = "", local_mail_host: str = "",
                 telegram_token: str = "",
                 whatsapp_token: str = "", whatsapp_sender: str = ""):
        """ initialize one or more different services for a sender of multiple notifications to individual receivers.

        :param smtp_server_uri: host and optional port and user credentials of email SMTP server to use, in the format:

                                [service://][user[:password]@]mail_server_host[:mail_server_port]

                                default SMTP ports are: 25 for basic SMTP, 465 for smtps/SSL or 587 for E-SMTP/TLS.
        :param mail_from:       email sender address.
        :param local_mail_host: FQDN of the local email host in the SMTP HELO/EHLO command.

        :param telegram_token:  token for the Telegram cloud API obtained from the @BotFather bot.

        :param whatsapp_token:  token for the WhatsApp cloud API obtained from the developer portal.
        :param whatsapp_sender: sender phone number id for the WhatsApp cloud API obtained from the developer portal.
        """
        # split smtp server URI into service, host, user, pw and port (all apart from the host address are optional)
        if '://' in smtp_server_uri:
            self._mail_service, smtp_server_uri = smtp_server_uri.split('://', maxsplit=1)
        else:
            self._mail_service = 'smtp'

        if '@' in smtp_server_uri:
            pos = smtp_server_uri.rindex("@")
            user_info = smtp_server_uri[:pos]
            mail_host = smtp_server_uri[pos + 1:]
            if ':' in user_info:
                pos = user_info.index(":")
                self._user_name = user_info[:pos]
                self._user_password = user_info[pos + 1:]
            else:
                self._user_name = user_info
                self._user_password = ""
        else:
            mail_host = smtp_server_uri
            self._user_name = ""
            self._user_password = ""

        if ':' in mail_host:
            pos = mail_host.rindex(":")
            port = int(_port) if (_port := mail_host[pos + 1:]).isnumeric() else 2_5
            mail_host = mail_host[:pos]
            if port != 2_5 and self._mail_service == 'smtp':
                self._mail_service = SMTP_PORT_SERVICE_NAMES.get(port, 'smtp')
        else:
            port = SMTP_SERVICE_NAME_PORTS.get(self._mail_service, 2_5)
        self._mail_host = mail_host
        self._mail_port = port

        self._mail_from = mail_from
        self._local_mail_host = local_mail_host or self._mail_host

        self._telegram_token = telegram_token

        self._whatsapp_token = whatsapp_token
        self._whatsapp_sender_id = whatsapp_sender

    def send_notification(self, msg_body: str, receiver: str, subject: str = "", msg_type: str = 'to_' + 'html') -> str:
        """ send a notification message with optional subject to receiver via the specified service.

        :param msg_body:        message body. line breaks are converted (br-tag <-> newline character) in accordance
                                with msg_type.
        :param receiver:        receiver address in the format ``service:address=name``, where ``service`` is mailto,
                                'telegram' or 'whatsapp', ``address`` is an email address, a chat id or phone number and
                                ``name`` is the name of the receiving person.
        :param subject:         optional subject text. added to the top of the msg_body for messenger services,
                                separated by an empty line. if not specified or specified as empty string or as
                                a single space character, then it will not be added to the top of the message body.
        :param msg_type:        message type ('html' or 'plain'), and optional conversion to it (if starts with 'to').
        :return:                error message on error or empty string if notification got send successfully.
        """
        service, addr_name = receiver.split(':')
        address, name = addr_name.split('=')
        if subject and subject != " " and service != 'mailto' and not subject.endswith('\n'):
            subject = f"{subject}\n\n"

        if service == 'mailto':
            err_msg = self.send_email(msg_body, address, subject, name, msg_type)
        elif service == 'telegram':
            err_msg = self.send_telegram(f"{subject}{msg_body}", address, name, msg_type)
        elif service == 'whatsapp':
            err_msg = self.send_whatsapp(f"{subject}{msg_body}", address, name, msg_type)
        else:
            err_msg = f"'{service}' notification service is not supported/implemented"

        return err_msg

    def send_email(self, msg_body: str, address: str, subject: str, name: str, msg_type: str = 'to_' + 'html') -> str:
        """ send email to the passed address.

        :param msg_body:        message body text. for new lines use newline char in plain and `<br>` in HTML texts.
        :param address:         email address of the receiver.
        :param subject:         email subject text.
        :param name:            name of the receiver.
        :param msg_type:        message type ('html' or 'plain'), and optional conversion to it (if starts with 'to').
        :return:                error message on error or empty string if notification email got send successfully.
        """
        err_prefix = f"error sending {msg_type} email to {name}: "

        if not self._mail_host:
            return f"{err_prefix}mail server not configured"

        msg_body, msg_type = _body_type_conversion(msg_body, msg_type)

        err_msg = ""
        try:
            message = MIMEText(msg_body, _subtype=msg_type)
            message['Subject'] = subject
            message['From'] = self._mail_from
            message['To'] = address
            # SMTP_SSL could throw "SSL:UNKNOWN_PROTOCOL" error
            service_class = SMTP_SSL if self._mail_port == 4_6_5 or self._mail_service == 'smtps' else SMTP
            with service_class(self._mail_host, self._mail_port, local_hostname=self._local_mail_host) as session:
                # session.set_debuglevel(1)
                session.ehlo()
                # using session.starttls() could throw error "STARTTLS extension not supported by server."
                if self._mail_service == 'smtpTLS':
                    session.starttls()
                if self._user_name:
                    session.login(self._user_name, self._user_password)
                unreached_recipients = session.send_message(message, self._mail_from, address)
                if unreached_recipients:
                    err_msg = f"{err_prefix}unreached email recipient '{unreached_recipients}'"
        except Exception as mex:    # pylint: disable=broad-exception-caught
            err_msg = f"{err_prefix}email send exception '{mex}'"

        return err_msg

    def send_telegram(self, msg_body: str, chat_id: str, name: str, msg_type: str = 'to_' + 'html') -> str:
        """ send message to the passed telegram chat id.

        :param msg_body:        message body text. the Telegram `HTML` format supports only a few tags
                                (see https://core.telegram.org/bots/api#html-style). on top of that you can
                                also include the following HTML tags, which will be either converted or removed:

                                * br: will be converted into a new line character.
                                * div: will be removed.

        :param chat_id:         chat id of the telegram receiver or group.
        :param name:            name of the receiver.
        :param msg_type:        message type ('html' or 'plain'), and optional conversion to it (if starts with 'to').
        :return:                error message on error or empty string if notification got send successfully.

        .. hint::
            see https://www.heise.de/select/ct/2023/8/2231816070982959290 for useful bots and tips.
            use https://telemetr.io/, https://lyzem.com/ or https://tgstat.com/ to search/find public channels/groups.
        """
        err_prefix = f"error sending '{msg_type}' Telegram message to '{name}': "

        if not self._telegram_token:
            return f"{err_prefix}missing token or sender id"

        msg_body, msg_type = _body_type_conversion(msg_body, msg_type)
        if msg_type == 'html':
            msg_body = msg_body.replace('<br>', '\n').replace('<br />', '\n').replace('<br/>', '\n')
            msg_body = re.sub(r'<div[^<]+?>', "", msg_body.replace('</div>', ""))

        post_data = {'chat_id': chat_id, 'text': msg_body[:TELEGRAM_MESSAGE_MAX_LEN]}
        if msg_type == 'html':
            post_data['parse_mode'] = 'HTML'    # https://core.telegram.org/bots/update56kabdkb12ibuisabdubodbasbdaosd

        err_msg = ""
        try:
            response = requests.post(f"https://api.telegram.org/bot{self._telegram_token}/sendMessage",
                                     json=post_data,
                                     timeout=(6.3, 96.3))    # connect-/read-timeouts
            if response.status_code != 200:
                err_msg = f"{err_prefix}{response.json()}"
        except Exception as tex:    # pylint: disable=broad-exception-caught
            err_msg = f"{err_prefix}{tex}"

        return err_msg

    def send_whatsapp(self, msg_body: str, receiver_id: str, name: str, msg_type: str = 'to_' + 'html') -> str:
        """ send message to the passed WhatsApp user/group.

        :param msg_body:        message body text. for new lines use newline char in plain and `<br>` in HTML texts.
        :param receiver_id:     phone number with country code (and a leading '+') of the WhatsApp receiver or the
                                id of the WA group (last part of the URL to invite somebody into the group).
        :param name:            name of the receiver.
        :param msg_type:        message type ('html' or 'plain'), and optional conversion to it (if starts with 'to').
                                recognized/converted HTML tags are b, br, i and pre.
        :return:                error message on error or empty string if notification got send successfully.

        using WA Business API (see: https://developers.facebook.com/docs/whatsapp/on-premises/reference/messages and
        https://github.com/Neurotech-HQ/heyoo/blob/58ad576c3dfaf05bad5f342bc8614cf0ba02e6ae/heyoo/__init__.py#L43)
        has the restriction that the receiver has first to send a message to the sender to get a window of 24 hours.
        and using pyWhatKit's web browser-based approach will not work on PythonAnywhere because web.whatsapp.com is not
        in their whitelist (https://www.pythonanywhere.com/whitelist/)
        """
        err_prefix = f"error sending '{msg_type}' WhatsApp message to '{name}': "

        if not self._whatsapp_token or not self._whatsapp_sender_id:
            return f"{err_prefix}missing token or sender id"

        is_group = not receiver_id.startswith('+')
        msg_body, msg_type = _body_type_conversion(msg_body, msg_type)
        if msg_type == 'html':
            msg_body = msg_body\
                .replace('<b>', '*').replace('</b>', '*') \
                .replace('<br>', '\n').replace('<br />', '\n').replace('<br/>', '\n') \
                .replace('<i>', '_').replace('</i>', '_') \
                .replace('<pre>', '```').replace('</pre>', '```')

        err_msg = ""
        try:
            response = requests.post(
                f"https://graph.facebook.com/v15.0/{self._whatsapp_sender_id}/messages",
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f"Bearer {self._whatsapp_token}"},
                json={
                    'messaging_product': 'whatsapp',
                    'recipient_type': 'group' if is_group else 'individual',
                    'to': receiver_id if is_group else receiver_id[1:].translate({ord(char): None for char in " /-"}),
                    'type': 'text',
                    'text': {'preview_url': True, 'body': msg_body[:WHATSAPP_MESSAGE_MAX_LEN]}},
                timeout=(6.3, 96.3))    # connect-/read-timeouts
            if response.status_code != 200:
                err_msg = f"{err_prefix}{response.json()}"
        except Exception as wex:    # pylint: disable=broad-exception-caught
            err_msg = f"{err_prefix}{wex}"

        return err_msg
