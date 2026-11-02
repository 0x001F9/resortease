from django.views import View
from django.shortcuts import render

from app.public_reservations import (
    PENDING_RESERVATION_SESSION_KEY,
    resume_pending_public_reservation,
)

from .models import (
    CHAT_SESSION_ID_SESSION_KEY,
    ChatMessageModel,
    get_or_create_active_chat_session,
    save_chat_message,
)


class ChatView(View):
    template_name = "chat.html"

    def get(self, request):
        if request.session.session_key is None:
            request.session.create()

        chat_session, _ = get_or_create_active_chat_session(
            request.session.session_key,
            request.user.pk if request.user.is_authenticated else None,
            request.session.get(CHAT_SESSION_ID_SESSION_KEY),
        )
        request.session[CHAT_SESSION_ID_SESSION_KEY] = chat_session.pk

        if (
            request.user.is_authenticated
            and PENDING_RESERVATION_SESSION_KEY in request.session
        ):
            reservation, _, _ = resume_pending_public_reservation(request)
            if reservation is not None:
                save_chat_message(
                    chat_session.pk,
                    ChatMessageModel.Role.ASSISTANT,
                    "Your reservation request has been saved to your account and is pending confirmation.",
                )

        return render(request, self.template_name)