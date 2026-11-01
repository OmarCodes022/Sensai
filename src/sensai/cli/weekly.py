"""`sensai <model> --weekly-run <folder>`: prepare the week's four outputs, print one line per output, exit."""
from sensai.campaign import CampaignStore
from sensai.core.messages import Message
from sensai.llm.structured import OllamaStructuredClient
from sensai.cli.approval import sanitize
from sensai.weekly.run import run_week


def line(outcome) -> str:
    return f"{outcome.name} {'.' * (13 - len(outcome.name))} {'OK' if outcome.ok else 'failed':7}{sanitize(outcome.detail)}"


def weekly_main(settings, args) -> int:
    """0 when every output is OK, 1 when one failed, 130 when stopped with Ctrl+C (nothing saved)."""
    client = OllamaStructuredClient(args.host, args.operation_timeout, context_length=settings.context_length)

    def ask(instructions: str, request: str, schema):
        messages = [Message(role="system", content=instructions), Message(role="user", content=request)]
        return client.complete(args.model, messages, schema)

    print(f"Preparing the week from {args.weekly_run} with {args.model}…")
    try:
        header, outcomes, saved = run_week(args.weekly_run, CampaignStore(settings.campaigns_dir), ask,
                                           settings.guardrails_file, on_step=lambda o: print(line(o), flush=True))
    except KeyboardInterrupt:
        print("\nStopped: nothing was saved.")
        return 130
    print(header)
    print(f"Saved {saved}: nothing was sent or published." if saved else "Nothing was saved, sent or published.")
    return 0 if all(o.ok for o in outcomes) else 1
