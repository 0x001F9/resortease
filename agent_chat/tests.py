from datetime import datetime, time, timedelta
from datetime import timezone as datetime_timezone
from django.test import SimpleTestCase
from django.test import TestCase
from django.utils import timezone
from langchain_core.messages import AIMessageChunk, ToolMessage
from unittest.mock import patch

from account.models import User
from agent_chat.context import AgentContext
from agent_chat.agent import agent
from agent_chat.consumers import _assistant_text_from_chunk
from agent_chat.functions.branches_facilities import get_branch, get_facility
from agent_chat.functions.current_time import get_current_datetime
from agent_chat.functions.reservations import (
    add_pending_reservation,
    auth_action_urls,
    check_reservation_availability,
    get_latest_reservation,
)
from agent_chat.models import (
    CHAT_SESSION_ID_SESSION_KEY,
    ChatMessageModel,
    ChatSessionModel,
)
from app.public_reservations import PENDING_RESERVATION_SESSION_KEY
from dashboard.models import Branch, Calendar, Facility, Payment, Reservation


class AgentToolTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Harbor Branch",
            slug="harbor-branch",
            city="Harbor City",
            address="1 Bay Road",
            phone_number="+15555550613",
            email="harbor@example.com",
            description="A quiet harbor resort.",
        )
        self.facility = Facility.objects.create(
            branch=self.branch,
            name="Garden Pool",
            slug="garden-pool",
            description="A heated pool.",
            capacity=12,
            rate_24hours=1000,
            rate_22hours=800,
            rate_morning=500,
            rate_evening=600,
            rate_per_extra_hour=75,
        )
        self.guest = User.objects.create_user(
            username="chatguest",
            email="chatguest@example.com",
            password="secret",
            first_name="Chat",
            last_name="Guest",
            phone_number_code="+1",
            phone_number="5551234500",
        )
        self.starts_at = timezone.make_aware(
            datetime.combine(timezone.localdate() + timedelta(days=2), time(8))
        )
        self.starts_at_text = timezone.localtime(self.starts_at).strftime(
            "%Y-%m-%dT%H:%M"
        )
        self.session = self.client.session
        self.session.create()
        self.context = AgentContext(
            user_id=None,
            first_name="User",
            session=self.session,
        )

    def runtime(self, context=None):
        from types import SimpleNamespace

        return SimpleNamespace(context=context or self.context)

    def reservation_args(self):
        return {
            "branch_name": self.branch.name,
            "facility_name": self.facility.name,
            "rate_package": "morning",
            "starts_at": self.starts_at_text,
            "party_size": 4,
            "special_requests": "Near the shallow end.",
        }

    def test_branch_and_facility_tools_return_requested_public_details(self):
        branch = get_branch.func(self.branch.name)[0]
        all_branches = get_branch.func(None)
        facility = get_facility.func(self.branch.name, None)[0]
        specific_facility = get_facility.func(
            self.branch.name,
            self.facility.name,
        )

        self.assertEqual(branch["city"], "Harbor City")
        self.assertEqual(branch["facilities"], ["Garden Pool"])
        self.assertEqual(len(all_branches), 1)
        self.assertIn("/branches/harbor-branch/", branch["page_url"])
        self.assertEqual(facility["capacity"], 12)
        self.assertEqual(facility["rates"]["per_extra_hour"], 75)
        self.assertEqual(len(specific_facility), 1)
        self.assertIn("/facilities/garden-pool/", facility["page_url"])

    def test_availability_uses_public_reservation_validation_and_conflicts(self):
        args = self.reservation_args()
        self.assertEqual(check_reservation_availability.func(**args), "Available.")

        Calendar.objects.create(
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(hours=9),
        )
        unavailable = check_reservation_availability.func(**args)
        self.assertTrue(unavailable.startswith("Unavailable:"))
        self.assertNotIn(self.guest.email, unavailable)

    def test_unauthenticated_reservation_is_staged_with_auth_actions(self):
        result = add_pending_reservation.func(
            **self.reservation_args(),
            runtime=self.runtime(),
        )

        self.session.load()
        self.assertIn("create an account", result)
        self.assertEqual(Reservation.objects.count(), 0)
        self.assertEqual(
            self.session[PENDING_RESERVATION_SESSION_KEY]["facility"],
            str(self.facility.pk),
        )
        self.assertTrue(self.context.requires_auth_actions)
        self.assertIn("next=%2Fchat%2F", auth_action_urls()["login_url"])

    def test_authenticated_reservation_is_created_pending(self):
        context = AgentContext(
            user_id=self.guest.pk,
            first_name=self.guest.first_name,
            session=self.session,
        )
        result = add_pending_reservation.func(
            **self.reservation_args(),
            runtime=self.runtime(context),
        )

        reservation = Reservation.objects.get()
        self.assertIn("pending confirmation", result)
        self.assertEqual(reservation.guest, self.guest)
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertEqual(
            reservation.rate_package,
            Reservation.RatePackage.MORNING,
        )
        self.assertEqual(reservation.special_requests, "Near the shallow end.")
        self.assertFalse(context.requires_auth_actions)

    def test_authenticated_reservation_rejects_existing_account_overlap(self):
        Reservation.objects.create(
            guest=self.guest,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(hours=9),
            status=Reservation.Status.CONFIRMED,
        )
        context = AgentContext(
            user_id=self.guest.pk,
            first_name=self.guest.first_name,
            session=self.session,
        )

        result = add_pending_reservation.func(
            **self.reservation_args(),
            runtime=self.runtime(context),
        )

        self.assertIn("already have a reservation", result)
        self.assertEqual(Reservation.objects.filter(guest=self.guest).count(), 1)

    def test_latest_reservation_is_private_and_includes_payments(self):
        reservation = Reservation.objects.create(
            guest=self.guest,
            facility=self.facility,
            starts_at=self.starts_at,
            ends_at=self.starts_at + timedelta(hours=9),
            party_size=3,
            special_requests="Window seats.",
            status=Reservation.Status.PENDING,
        )
        Payment.objects.create(
            reservation_id=reservation,
            name="Deposit",
            amount="100.00",
            method="card",
            status=Payment.Status.SUCCEEDED,
        )
        context = AgentContext(
            user_id=self.guest.pk,
            first_name=self.guest.first_name,
            session=self.session,
        )

        latest = get_latest_reservation.func(runtime=self.runtime(context))

        self.assertEqual(latest["facility"], self.facility.name)
        self.assertEqual(latest["party_size"], 3)
        self.assertEqual(latest["special_requests"], "Window seats.")
        self.assertEqual(len(latest["payments"]), 1)
        self.assertEqual(latest["payments"][0]["amount"], "100.00")

    def test_unauthenticated_latest_reservation_requests_authentication(self):
        result = get_latest_reservation.func(runtime=self.runtime())

        self.assertIn("sign in or create an account", result)
        self.assertTrue(self.context.requires_auth_actions)

    @patch("django.utils.timezone.now")
    def test_current_datetime_tool_returns_resort_local_time(self, mock_now):
        mock_now.return_value = datetime(
            2026,
            11,
            1,
            16,
            30,
            tzinfo=datetime_timezone.utc,
        )

        result = get_current_datetime.func()

        self.assertEqual(result["date"], "2026-11-02")
        self.assertEqual(result["time"], "00:30:00")
        self.assertEqual(result["weekday"], "Monday")
        self.assertEqual(result["timezone"], "Asia/Manila")
        self.assertEqual(result["datetime"], "2026-11-02T00:30:00+08:00")


class ChatReservationResumeTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Harbor Branch",
            slug="harbor-branch",
            city="Harbor City",
            address="1 Bay Road",
        )
        self.facility = Facility.objects.create(
            branch=self.branch,
            name="Garden Pool",
            slug="garden-pool",
            rate_morning=500,
        )
        self.guest = User.objects.create_user(
            username="returnguest",
            email="returnguest@example.com",
            password="secret",
            first_name="Return",
            last_name="Guest",
            phone_number_code="+1",
            phone_number="5551234501",
        )

    def test_authenticated_chat_resumes_and_confirms_a_staged_reservation_once(self):
        self.client.get("/chat/")
        session = self.client.session
        chat_session_id = session[CHAT_SESSION_ID_SESSION_KEY]
        chat_session = ChatSessionModel.objects.get(pk=chat_session_id)
        ChatMessageModel.objects.create(
            session=chat_session,
            role=ChatMessageModel.Role.ASSISTANT,
            content="Earlier chat message.",
        )

        self.client.force_login(self.guest)
        starts_at = timezone.make_aware(
            datetime.combine(timezone.localdate() + timedelta(days=2), time(8))
        )
        session = self.client.session
        session[PENDING_RESERVATION_SESSION_KEY] = {
            "branch_id": self.branch.pk,
            "facility": str(self.facility.pk),
            "rate_package": "morning",
            "starts_at": timezone.localtime(starts_at).strftime("%Y-%m-%dT%H:%M"),
            "days": 1,
            "party_size": 2,
            "special_requests": "Please call on arrival.",
        }
        session.save()

        response = self.client.get("/chat/")

        self.assertEqual(response.status_code, 200)
        reservation = Reservation.objects.get()
        self.assertEqual(reservation.guest, self.guest)
        chat_session = ChatSessionModel.objects.get(pk=chat_session_id)
        self.assertEqual(chat_session.user, self.guest)
        self.assertEqual(
            ChatMessageModel.objects.filter(
                session=chat_session,
                role=ChatMessageModel.Role.ASSISTANT,
            ).count(),
            2,
        )
        self.assertIn(
            "saved to your account",
            ChatMessageModel.objects.filter(
                session=chat_session,
                role=ChatMessageModel.Role.ASSISTANT,
            ).order_by("-id").first().content,
        )

        self.client.get("/chat/")
        self.assertEqual(Reservation.objects.count(), 1)


class DynamicPromptTests(SimpleTestCase):
    def test_dynamic_prompt_uses_first_name_or_generic_user_name(self):
        from types import SimpleNamespace

        from agent_chat.agent import dynamic_prompt

        authenticated = SimpleNamespace(
            runtime=SimpleNamespace(
                context=AgentContext(
                    user_id=1,
                    first_name="Ada",
                    session=None,
                )
            )
        )
        anonymous = SimpleNamespace(runtime=SimpleNamespace(context=None))

        authenticated_prompt = dynamic_prompt(authenticated)
        anonymous_prompt = dynamic_prompt(anonymous)

        self.assertIn("The user is authenticated.", authenticated_prompt)
        self.assertIn("first name: Ada.", authenticated_prompt)
        self.assertIn("morning rate has a fixed time of 8:00 AM to 5:00 PM", authenticated_prompt)
        self.assertIn(
            "evening rate has a fixed time of 7:00 PM to 6:00 AM the following day",
            authenticated_prompt,
        )
        self.assertIn("The user is not authenticated.", anonymous_prompt)
        self.assertIn("Address them as User.", anonymous_prompt)


class AssistantStreamFilteringTests(SimpleTestCase):
    def test_streams_assistant_text_only(self):
        assistant_chunk = AIMessageChunk(content="Here is a concise summary.")
        tool_chunk = ToolMessage(
            content="[agent_chat/rag/docs/resort.md]\nRaw document text",
            tool_call_id="search-1",
        )

        self.assertEqual(
            _assistant_text_from_chunk(assistant_chunk, {"langgraph_node": "model"}),
            "Here is a concise summary.",
        )
        self.assertEqual(
            _assistant_text_from_chunk(tool_chunk, {"langgraph_node": "tools"}),
            "",
        )
        self.assertEqual(
            _assistant_text_from_chunk(assistant_chunk, {"langgraph_node": "tools"}),
            "",
        )


def main():
    response = agent.invoke({
        "messages": [
            {
                "role": "user",
                "content": "Hello, who are you?"
            }
        ]
    },
        config={
            "debug": True,
            "configurable": {
                "thread_id": "manual-test-session",
                "debug_model": True,
            },
        },
    )

    print("==== Response ====")
    print(response["messages"][-1].content)


if __name__ == "__main__":
    main()
