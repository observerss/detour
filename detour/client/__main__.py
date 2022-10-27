import os
import logging

os.environ.setdefault("DETOUR_CMD", "client")

from .client import main


main()
