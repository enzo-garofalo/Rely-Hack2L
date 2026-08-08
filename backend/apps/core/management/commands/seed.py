"""Compatibility alias for the canonical ``seed_demo`` command."""

from .seed_demo import Command as SeedDemoCommand


class Command(SeedDemoCommand):
    help = "Alias compatível de seed_demo. Restaura o dataset congelado da demo."
