#!/usr/bin/env python3
"""Start a vLLM server whose JSON grammar forbids whitespace.

vLLM 0.8.5 accepts backend options only as ``backend:option`` inside
``DecodingConfig``, whose validation strips the option before checking the name.
The command-line parser, however, restricts ``--guided-decoding-backend`` to a
fixed ``choices`` list and rejects the option form outright, so the value is set
after parsing instead. This keeps the V1 engine: its per-request equivalent is
not honoured, because V1 builds one backend from server config.

Without this, greedy decoding can settle on a separator fixed point once a JSON
field is complete and emit whitespace until the output cap, discarding a
finished answer as a decode error.
"""

import os
import sys

from vllm.entrypoints.openai.api_server import run_server
from vllm.entrypoints.openai.cli_args import make_arg_parser, validate_parsed_serve_args
from vllm.utils import FlexibleArgumentParser

# xgrammar cannot compile a schema containing maxItems and, under "auto", vLLM
# silently falls back to a backend that permits arbitrary whitespace. The helper
# schemas omit maxItems; the actor must use its own compatible server. guidance
# returned empty decisions even for known triggers in the September 18 probe.
BACKEND = os.environ.get("PM_GUIDED_BACKEND", "xgrammar:disable-any-whitespace")


def main(argv=None):
    parser = make_arg_parser(FlexibleArgumentParser(description=__doc__))
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    # Set after parsing: the parser's choices list has no option-bearing entry.
    args.guided_decoding_backend = BACKEND
    validate_parsed_serve_args(args)
    print(f"guided_decoding_backend={args.guided_decoding_backend}", flush=True)
    import asyncio
    asyncio.run(run_server(args))


if __name__ == "__main__":
    main()
