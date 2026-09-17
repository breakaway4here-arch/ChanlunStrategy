"""Small CSS readers for media-query contracts in frontend tests."""


def media_rule_blocks(css, rule):
    """Return the balanced brace contents for every exact at-rule prefix."""
    blocks = []
    cursor = 0
    while True:
        start = css.find(rule, cursor)
        if start < 0:
            break
        opening = css.find("{", start + len(rule))
        if opening < 0:
            break
        depth = 0
        quote = None
        escaped = False
        in_comment = False
        end = None
        index = opening
        while index < len(css):
            char = css[index]
            following = css[index + 1] if index + 1 < len(css) else ""
            if in_comment:
                if char == "*" and following == "/":
                    in_comment = False
                    index += 2
                    continue
                index += 1
                continue
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                index += 1
                continue
            if char == "/" and following == "*":
                in_comment = True
                index += 2
                continue
            if char in ("'", '"'):
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index
                    break
            index += 1
        if end is None:
            break
        blocks.append(css[opening + 1 : end])
        cursor = end + 1
    return blocks
