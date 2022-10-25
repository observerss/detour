import os

os.environ.setdefault("DETOUR_CMD", "client")

from .client import main

main()
