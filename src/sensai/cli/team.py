"""/team in the terminal: every agent's step and handoff is shown; only the brief and the final draft join the chat."""
from sensai.chat.agents import team
from sensai.chat.reasoning import Section
from sensai.core.cancellation import OperationCancelled, OperationTimedOut
from sensai.core.errors import SensaiError
from sensai.core.messages import Message
from sensai.guardrails.rules import message_for


def team_command(session, brief: str, checker, facts: str, guard, new_token, write, recorder=None) -> bool:
    """True when the final draft was added to the conversation (and saved)."""
    client = getattr(session.client, "client", session.client)  # Drafts in between are not checked, the final one is.
    tokens, line_start, result = [], True, None

    def token():
        tokens.append(new_token())
        return tokens[-1]

    def show(item) -> None:
        nonlocal line_start
        if isinstance(item, Section):
            write(("" if line_start else "\n") + item.title)
            line_start = True
        elif item:
            write(item, end="", flush=True)
            line_start = item.endswith("\n")

    stream = team(brief, client, checker, session.model, facts, token)
    try:
        while True:
            try:
                show(next(stream))
            except StopIteration as stop:
                result = stop.value
                break
    except (KeyboardInterrupt, OperationCancelled):
        if tokens:
            tokens[-1].cancel()
        write("\nTeam stopped: nothing was added.")
        return False
    except OperationTimedOut:
        write("\nTeam stopped: the time limit was reached, nothing was added.")
        return False
    except SensaiError as exc:
        write(f"\nerror: {exc}")
        return False
    finally:
        stream.close()
    if guard is not None and not (decision := guard.inspect(result.draft, "output")).allowed:
        write(f"Final draft blocked: {message_for(decision.reason)} Nothing was added.")
        return False
    revised = f" ({result.revisions} revision{'s' * (result.revisions != 1)})" if result.revisions else ""
    write(f"\nFinal draft{revised}\n{result.answer}")
    session.messages += [Message(role="user", content=f"/team {brief}"), Message(role="assistant", content=result.answer)]
    if recorder is not None:
        recorder.after_turn(session)
    return True
