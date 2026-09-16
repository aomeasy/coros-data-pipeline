def _run(*args, stdin_input=None):
    """เรียก coros-mcp command"""
    cmd = ["npx", "coros-mcp"] + list(args)
    result = subprocess.run(
        cmd,
        input=stdin_input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=True,
    )
    if result.stdout is None:
        result.stdout = ""
    if result.stderr is None:
        result.stderr = ""
    return result