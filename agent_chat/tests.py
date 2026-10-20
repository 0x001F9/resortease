from django.test import TestCase

from account.models import User
from agent_chat.models import AgentChatMessage, AgentChatSession


class AgentChatModelTests(TestCase):
    def setUp(self):
        self.employee = User.object.create(
            username="chat_employee",
            role=User.Role.Employee,
            phone_number_code="+1",
            phone_number="5551234501",
            email="chat_employee@example.com",
            first_name="Chat",
            last_name="Employee",
        )
        self.guest = User.object.create(
            username="chat_guest",
            role=User.Role.User,
            phone_number_code="+1",
            phone_number="5551234502",
            email="chat_guest@example.com",
            first_name="Chat",
            last_name="Guest",
        )

    def test_anonymous_chat_can_be_taken_over_by_employee(self):
        chat = AgentChatSession.objects.create(
            anonymous_user_id="visitor-token",
            status=AgentChatSession.Status.HUMAN_ACTIVE,
            assigned_employee=self.employee,
        )
        guest_message = AgentChatMessage.objects.create(
            chat=chat,
            sender_type=AgentChatMessage.SenderType.GUEST,
            body="I need help with my booking.",
        )
        employee_message = AgentChatMessage.objects.create(
            chat=chat,
            user=self.employee,
            sender_type=AgentChatMessage.SenderType.EMPLOYEE,
            body="I can help with that.",
        )

        self.assertIsNone(chat.user)
        self.assertEqual(chat.assigned_employee, self.employee)
        self.assertIsNone(guest_message.user)
        self.assertTrue(guest_message.is_from_guest)
        self.assertEqual(employee_message.user, self.employee)
        self.assertEqual(employee_message.sender_name, "Chat Employee")
        self.assertEqual(chat.last_message, "I can help with that.")
        self.assertEqual(chat.unread_count, 2)

    def test_authenticated_chat_and_messages_link_to_the_user(self):
        chat = AgentChatSession.objects.create(user=self.guest)
        message = AgentChatMessage.objects.create(
            chat=chat,
            user=self.guest,
            sender_type=AgentChatMessage.SenderType.GUEST,
            body="Hello.",
            is_read=True,
        )

        self.assertEqual(chat.user, self.guest)
        self.assertEqual(message.user, self.guest)
        self.assertEqual(chat.last_message, "Hello.")
        self.assertEqual(chat.unread_count, 0)
