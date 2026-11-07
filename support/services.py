from config.errors import NotFoundError, PermissionDeniedError
from support.models import Ticket, TicketMessage
from users.models import BaseUser


def create_ticket(*, user: BaseUser, subject: str, message: str) -> Ticket:
    ticket = Ticket.objects.create(user=user, subject=subject)
    TicketMessage.objects.create(ticket=ticket, sender=user, message=message, is_admin_reply=False)
    return ticket


def get_ticket_for_user(*, user: BaseUser, ticket_id: int) -> Ticket:
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        raise NotFoundError("Ticket not found.")
    if ticket.user_id != user.id and not user.is_staff:
        raise PermissionDeniedError("Not your ticket.")
    return ticket


def add_message(*, ticket: Ticket, sender: BaseUser, message: str) -> TicketMessage:
    is_admin_reply = sender.is_staff and sender.id != ticket.user_id
    ticket_message = TicketMessage.objects.create(
        ticket=ticket, sender=sender, message=message, is_admin_reply=is_admin_reply
    )
    ticket.status = Ticket.Status.PENDING if is_admin_reply else Ticket.Status.OPEN
    ticket.save(update_fields=["status", "updated_at"])
    return ticket_message


def close_ticket(*, ticket: Ticket) -> Ticket:
    ticket.status = Ticket.Status.CLOSED
    ticket.save(update_fields=["status", "updated_at"])
    return ticket
