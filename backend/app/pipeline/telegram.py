"""Minimal Telegram Bot API client for the confirm-to-send flow.

Uses long polling (getUpdates) so no public webhook is needed. All methods are
synchronous; the service calls them from a worker thread. The confirm flow:

    poll -> prep receipt -> send_payment_notification() (PDF + Confirm/Hold)
    user taps Confirm -> callback -> processor.send_one(reference) -> emailed
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx


def confirm_keyboard(reference: str) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm & Send", "callback_data": f"confirm:{reference}"},
                {"text": "⏸ Hold", "callback_data": f"hold:{reference}"},
            ]
        ]
    }


class TelegramBot:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base = f"https://api.telegram.org/bot{token}"

    # --- low level ------------------------------------------------------
    def _post(self, method: str, **payload) -> Dict[str, Any]:
        r = httpx.post(f"{self.base}/{method}", json=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    def _edit(self, method: str, **payload) -> Dict[str, Any]:
        """Like _post but tolerates Telegram's benign 'message is not modified'."""
        r = httpx.post(f"{self.base}/{method}", json=payload, timeout=30)
        data = r.json()
        if not data.get("ok") and "not modified" in data.get("description", ""):
            return data
        r.raise_for_status()
        return data

    def get_me(self) -> Dict[str, Any]:
        r = httpx.get(f"{self.base}/getMe", timeout=15)
        r.raise_for_status()
        return r.json()

    # --- sending --------------------------------------------------------
    def send_message(
        self, text: str, reply_markup: Optional[dict] = None, parse_mode: str = "HTML"
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": self.chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._post("sendMessage", **payload)

    def send_document(
        self,
        file_path: str,
        caption: Optional[str] = None,
        reply_markup: Optional[dict] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {"chat_id": self.chat_id}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "HTML"
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        with open(file_path, "rb") as fh:
            files = {"document": (os.path.basename(file_path), fh, "application/pdf")}
            r = httpx.post(f"{self.base}/sendDocument", data=data, files=files, timeout=60)
        r.raise_for_status()
        return r.json()

    # --- editing / callbacks -------------------------------------------
    def answer_callback(self, callback_query_id: str, text: str = "") -> Dict[str, Any]:
        return self._post("answerCallbackQuery", callback_query_id=callback_query_id, text=text)

    def edit_caption(
        self, message_id: int, caption: str, reply_markup: Optional[dict] = None
    ) -> Dict[str, Any]:
        """Update a message's caption and, optionally, its inline keyboard in one call.

        Pass reply_markup={"inline_keyboard": []} to also remove the buttons.
        """
        payload: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "message_id": message_id,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._edit("editMessageCaption", **payload)

    def clear_buttons(self, message_id: int) -> Dict[str, Any]:
        return self._edit(
            "editMessageReplyMarkup",
            chat_id=self.chat_id,
            message_id=message_id,
            reply_markup={"inline_keyboard": []},
        )

    # --- polling --------------------------------------------------------
    def get_updates(self, offset: Optional[int] = None, timeout: int = 25) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"timeout": timeout, "allowed_updates": '["callback_query"]'}
        if offset is not None:
            params["offset"] = offset
        r = httpx.get(f"{self.base}/getUpdates", params=params, timeout=timeout + 10)
        r.raise_for_status()
        return r.json().get("result", [])

    # --- high level -----------------------------------------------------
    def send_payment_notification(self, detail: Dict[str, Any]) -> Dict[str, Any]:
        """detail is one processed entry from PaymentProcessor prep output."""
        caption = (
            "\U0001f3e0 <b>New rent payment</b>\n"
            f"Tenant: <b>{detail.get('tenant')}</b>\n"
            f"Amount: <b>${detail.get('amount'):.2f}</b>\n"
            f"Period: {detail.get('period')}\n"
            f"Invoice: #{detail.get('invoice_no')}\n"
            f"Ref: <code>{detail.get('ref')}</code>\n\n"
            "Review the attached receipt, then <b>Confirm &amp; Send</b> to email it."
        )
        return self.send_document(
            detail["receipt"], caption=caption, reply_markup=confirm_keyboard(detail["ref"])
        )
