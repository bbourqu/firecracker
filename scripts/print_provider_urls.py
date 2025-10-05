#!/usr/bin/env python3
"""CLI helper: print resolved provider URLs (env > config > default).

Usage: python scripts/print_provider_urls.py [provider...]
"""
import sys
from utils.provider_resolver import resolve_provider_url


def main(argv):
    providers = argv[1:] or ['ollama', 'openai']
    for p in providers:
        print(f"{p}: {resolve_provider_url(p)}")


if __name__ == '__main__':
    main(sys.argv)
