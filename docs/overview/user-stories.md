# User stories

Eight stories follow Nadia, solo creator of the fictional skincare brand Serein
Studio, through her week. Together they cover every feature.

### Story 1: Prepare posts with the right persona

As a solo skincare creator, I want to draft captions with a writing persona, built-in or my own, and then switch to the community persona in the same chat, so that each task gets the right tone without losing what I already said.

Features: Base chat (B1), Personas (A5)

### Story 2: Pick up where I left off

As a creator who works in short sessions, I want to resume my own earlier chats with my preferences already known, so that I can continue the next day without repeating myself.

Features: Sessions and profile (M1), Personas (A5)

### Story 3: Check my numbers with Python instead of guessing

As a creator who reports on her weekly reach, I want to compute my figures with Python on my exported data, so that my report holds real numbers, not invented ones.

Features: Tools, Python sandbox

### Story 4: Stay in control when something goes wrong

As a creator who is not a developer, I want to understand every error and stop anything at any time, so that a failure never breaks my chat or runs code I did not approve.

Features: Base chat (B1), Sessions and profile (M1), Tools, Python sandbox

### Story 5: Get real numbers even when the first try fails

As a skincare creator, I want Sensai to compute my engagement figures with code and fix its own mistakes, so that my weekly report uses real numbers without me debugging Python.

Features: Python sandbox, Self-correcting code (T2)

### Story 6: Approve every run and choose what the code sees

As a creator, I want to approve code before it runs and control which files it sees, so that nothing runs on my computer without my say.

Features: Python sandbox, Self-correcting code (T2), Sessions and profile (M1)

### Story 7: See how Sensai reached its answer

As a skincare creator, I want to see how Sensai planned, which tools it used and how it checked a post, so that I can trust its figures and know it didn't slip in a claim I'm not allowed to make.

Features: Reasoning step by step (A1), Tools

### Story 8: Never wait forever for a flawed answer

As a creator, I want Sensai to stop after a fixed number of steps and tell me what is still wrong, so that I never wait forever or get a flawed answer presented as final.

Features: Reasoning step by step (A1), Base chat (B1)

## Coverage

| Feature | Stories |
| --- | --- |
| Base chat (B1) | 1, 4, 8 |
| Personas (A5) | 1, 2 |
| Sessions and profile (M1) | 2, 4, 6 |
| Tools | 3, 4, 7 |
| Python sandbox | 3, 4, 5, 6 |
| Self-correcting code (T2) | 5, 6 |
| Reasoning step by step (A1) | 7, 8 |
