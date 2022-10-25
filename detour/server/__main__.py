import os

os.environ.setdefault("DETOUR_CMD", "server")

from .server import main

main()
