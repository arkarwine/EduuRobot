# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

import asyncio
import logging
import sys

from hydrogram import idle

from .bot import Eduu
from .database import database
from .utils import http

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s.%(funcName)s | %(levelname)s | %(message)s",
    datefmt="[%X]",
)

# To avoid some annoying log
logging.getLogger("hydrogram.syncer").setLevel(logging.WARNING)
logging.getLogger("hydrogram.client").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

async def main():
    eduu = Eduu()

    try:
        # start the bot
        await database.connect()
        await eduu.start()

        if "test" not in sys.argv:
            await idle()
    except KeyboardInterrupt:
        # exit gracefully
        logger.warning("Forced stop… Bye!")
    finally:
        # close https connections and the DB if open
        await eduu.stop()
        await http.close()
        if database.is_connected:
            await database.close()


if __name__ == "__main__":
    asyncio.run(main())
