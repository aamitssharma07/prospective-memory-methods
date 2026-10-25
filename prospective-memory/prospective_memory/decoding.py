"""Decoder-level safeguard shared by the diagnostic harness and benchmark runner.

A JSON grammar permits unbounded whitespace between tokens. Greedy decoding can
therefore settle on a separator fixed point once a field is complete and emit
newlines until the output cap, so a finished answer is discarded as a decode
error and reads downstream as deliberate silence. Whether a server allows this
is a property of how it was started, not of the prompt, so it is measured.
"""

PROBE_SCHEMA = {"type": "object", "properties": {"label": {"type": "string", "maxLength": 40}},
                "required": ["label"], "additionalProperties": False}
PROBE_PROMPT = ("Return JSON matching the schema with label set to ready. Format the object "
                "across several indented lines.")
WHITESPACE_REMEDY = (
    "Server JSON grammar permits repeatable whitespace, so greedy decoding can emit "
    "separator runs until the token cap and discard completed answers. Start the server "
    "with prospective_memory/serve.py, which sets --guided-decoding-backend "
    "'xgrammar:disable-any-whitespace' after argument parsing because the parser's "
    "choices list rejects the option form. The per-request field is not a substitute: "
    "V1 builds one backend from server config and strips per-request options.")


def unbounded_whitespace(raw):
    """Report repeatable whitespace between JSON tokens, ignoring string contents.

    xgrammar's whitespace-free mode still emits one fixed separator space after
    a colon or comma, which cannot repeat and so cannot loop. The hazard is
    whitespace the grammar will accept indefinitely: a line break, a tab, or a
    run of spaces. Only those are reported.
    """
    # Only a single trailing newline is discounted: a trailing run is precisely
    # the separator loop this detects, so it must not be stripped away.
    text = raw.lstrip()
    if text.endswith("\n") and not text.endswith("\n\n"):
        text = text[:-1]
    in_string = escaped = False
    spaces = 0
    for character in text:
        if escaped:
            escaped = False
        elif in_string and character == "\\":
            escaped = True
        elif character == '"':
            in_string = not in_string
        elif not in_string:
            if character in "\t\n\r":
                return True
            spaces = spaces + 1 if character == " " else 0
            if spaces > 1:
                return True
    return False


def probe_compact_decoding(generate_raw):
    """Ask for indented output; a whitespace-free grammar cannot comply.

    ``generate_raw(system, payload, schema)`` returns the raw completion text.
    Whitespace here proves the trap is armed for every later structured call.
    """
    raw = generate_raw(PROBE_PROMPT, {"instruction": "emit the label"}, PROBE_SCHEMA)
    return not unbounded_whitespace(raw or "")
