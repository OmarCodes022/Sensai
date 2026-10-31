## Story 1

As a skincare creator, I want a weekly campaign document that Sensai updates piece by piece, so that my plan builds up over the session instead of being lost in the chat

- Each `/campaign` edit (terminal or the web Campaign page) changes one item in one section
- The other sections stay exactly the same in the saved file
- The document is still there after a restart

## Story 2

As a creator, I want sections I approved to stay protected, so that Sensai never silently rewrites work I already signed off

- `/campaign approve <section>` (or Approve section on the page) marks the section approved
- A change to an approved section is only applied after I confirm it
- A failed or refused edit leaves the file unchanged
