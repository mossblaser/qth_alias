import asyncio
import logging

from argparse import ArgumentParser

from qth_alias import AliasServer, __version__


def main():
    parser = ArgumentParser(
        description="A service which creates aliases for Qth paths.")
    parser.add_argument("--cache", "-c", default="aliases.json",
                        help="Filename of alias cache (default %(default)s).")
    parser.add_argument("--prefix", "-p", default="meta/alias/",
                        help="Prefix for control events/properties "
                             "(default %(default)s).")
    parser.add_argument("--host", "-H", default=None,
                        help="Qth server hostname.")
    parser.add_argument("--port", "-P", default=None, type=int,
                        help="Qth server port.")
    parser.add_argument("--keepalive", "-K", default=10, type=int,
                        help="MQTT Keepalive interval (seconds).")
    parser.add_argument("--quiet", "-q", default=False, action="store_true",
                        help="Only report errors.")
    parser.add_argument("--debug", default=False, action="store_true",
                        help="(Development only) Run asyncio in debug mode.")
    parser.add_argument("--version", "-V", action="version",
                        version="%(prog)s {}".format(__version__))
    args = parser.parse_args()

    if not args.quiet:
        logging.basicConfig(level=logging.INFO)

    loop = asyncio.get_event_loop()
    if not args.debug:
        loop.set_debug(True)

    s = AliasServer(cache_file=args.cache,
                    prefix=args.prefix,
                    host=args.host,
                    port=args.port,
                    keepalive=args.keepalive,
                    loop=loop)

    try:
        loop.run_until_complete(s.async_init())
        loop.run_forever()
    except KeyboardInterrupt:
        loop.run_until_complete(s.close())


if __name__ == "__main__":
    main()
