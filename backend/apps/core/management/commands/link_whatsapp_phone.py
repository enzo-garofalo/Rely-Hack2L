"""Liga um número de WhatsApp real a um cliente do cadastro (E10).

O `handle_inbound_whatsapp` (order_service.py) resolve telefone -> cliente
pelo cadastro e NUNCA cria cliente sozinho (guardrail #1: dado comercial
vem do cadastro, não do canal). Então, antes de mandar a primeira mensagem
do celular de verdade, o número precisa estar em algum `Customer` — é isso
que este comando faz, sem abrir o admin no meio da demo.

    python manage.py link_whatsapp_phone --customer 1 --phone "+55 11 99999-1234"

Atenção: `POST /api/demo/reset` roda flush + seed e devolve os telefones
do dataset congelado. Depois de cada reset, rode este comando de novo.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.core import whatsapp
from apps.core.models import Customer


class Command(BaseCommand):
    help = "Liga um número de WhatsApp real a um cliente existente (E10)."

    def add_arguments(self, parser):
        parser.add_argument("--customer", type=int, required=True, help="id do Customer")
        parser.add_argument("--phone", type=str, required=True, help="telefone com DDI, ex.: +55 11 99999-1234")

    def handle(self, *args, **options):
        digits = whatsapp.normalize_phone(options["phone"])
        if len(digits) < 10:
            raise CommandError(f"telefone inválido: '{options['phone']}' (use DDI + DDD + número)")

        try:
            customer = Customer.objects.get(pk=options["customer"])
        except Customer.DoesNotExist as exc:
            raise CommandError(f"cliente {options['customer']} não existe") from exc

        # Dois clientes com o mesmo final tornariam o roteamento ambíguo, e
        # ambiguidade não é resolvida em silêncio (guardrail #6): o inbound
        # recusaria a mensagem. Melhor barrar aqui, com o número na mão.
        conflicts = [
            other
            for other in Customer.objects.exclude(pk=customer.pk).exclude(phone="")
            if whatsapp.normalize_phone(other.phone)[-8:] == digits[-8:]
        ]
        if conflicts:
            names = ", ".join(f"#{c.pk} {c.name}" for c in conflicts)
            raise CommandError(f"telefone conflita com outro cliente ({names})")

        customer.phone = digits
        customer.save(update_fields=["phone"])
        self.stdout.write(
            self.style.SUCCESS(f"Cliente #{customer.pk} ({customer.name}) agora atende por {digits}.")
        )
