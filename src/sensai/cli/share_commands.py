"""/share and /unshare in the terminal (X3): a public link only after the exact content and URL are approved."""
from sensai.core.ports import ApprovalRequest
from sensai.share import ShareError


def share_command(shares, campaign, guard, approval, argument: str, write) -> None:
    section = argument.strip()
    if not section:
        write("usage: /share posts|report|calendar")
        return
    try:
        token, url, text = shares.propose(guard, campaign.latest(), section)
    except ShareError as exc:
        write(f"Not shared: {exc}")
        return
    request = ApprovalRequest(action="publish a public, no-login page", resource=url,
                              reason="anyone on the local network with the link can read it", content=text)
    if approval is None or not approval.request(request).approved:
        write("Nothing was shared.")
        return
    shares.publish(token, text)
    write(f"Shared: {url}   (remove with /unshare {token}; serve it with: python -m sensai.share)")


def unshare_command(shares, argument: str, write) -> None:
    token = argument.strip()
    if not token:
        listed = shares.list()
        write("usage: /unshare <token>" + (f"\nShared now: {', '.join(listed)}" if listed else "\nNothing is shared."))
    elif shares.remove(token):
        write(f"Removed: {shares.url(token)} now answers 404.")
    else:
        write(f"No share {token}.")
