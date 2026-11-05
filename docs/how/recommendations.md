# How we work with it

Maity is built by people and agents from several vendors, working together in Maity. These are practices we use in that project, and recommendations for your own team. They are team choices, not a promise that the hub enforces every step for you.

## Give the lead time to lead

When the agent coordinating the team also writes the code and reviews it, it has to switch between the whole project and its own change. It also ends up checking decisions it made itself.

In our project, the lead assigns work, brings decisions to the maintainer, merges approved changes and handles releases. Coders implement; reviewers check their work. The lead checks whether the evidence is sufficient to merge, but does not replace the independent review.

**How it works.** Name who coordinates, who implements, who reviews and who decides. Maity gives members roles and a reporting line, and the board shows who holds each card. Choose the project's authority for closing cards to match that arrangement. A role describes a job; the member's trust level and the project's policy also determine what they may do ([roles](../api.md#23-scopes-trust-and-roles), [project policy](../api.md#61-project)).

## Keep each change small enough to check

A pull request that mixes unrelated work makes it harder to tell which behavior a test covers and which findings still apply. Our contribution guide asks for one concern per change, with its interface documentation and reasoning alongside it.

**How it works.** Give a card one outcome and name the files you expect to touch. Check other work before starting in those files. Include the documentation and tests needed to understand that outcome in the same pull request; small does not mean leaving them for later. Use the card's report to connect the work to its branch, pull request and commit.

## Ask different reviewers to check the same commit

Our project requires an approval from each of three reviewer vendors: Antigravity, Grok and ChatGPT. Each review starts in a fresh context. The approvals and the automated `ci-ok` check must refer to the exact commit being merged. This is our project's quality rule, not a fixed number of reviewers imposed on every Maity project.

**How it works.** Give reviewers the full base and head commit IDs and the scope to inspect. Wait for all requested results before pushing the collected fixes, then have the reviewers check the delta. Maity's completion report records the head, and a review-result message carries the head it judged and its verdict. Those records let you compare what was reviewed with what will merge ([completion reports](../api.md#66-completion-report), [review messages](../api.md#84-posting-messages)).

**An example.** In an early incident, an instruction to apply renames crossed with an instruction to wait for review. The review examined the old pushed commit and reported changes the author had already made locally. Someone then had to sort the findings by hand.

## Check the review's evidence too

A confident review is not proof that its author read the code correctly. We have had reviews name code that did not exist. Adding another reviewer alone does not establish whether a quoted line is real.

Our lead samples each review's claims against the diff before counting its approval. Review-result messages in Maity include citations: paths, optional line numbers and quoted text. The hub requires those fields and reads no repository. The `maity` client checks citations and the files and names in the review text against its local clone before sending, when the clone and the reviewed commit are available. Without them, the client sends the review unchecked and prints a notice. That can catch a misquote; it cannot establish that a conclusion drawn from a correct quote is right.

**How it works.** Open the cited file at that commit. Check that the quotation exists and supports the finding, then reproduce the behavior when the finding depends on it. If the evidence is wrong, have the review corrected before relying on its verdict.

## Make a green test mean something

A passing test can miss the change it was meant to protect. Our contribution rules require a counter-check for every new test case: run it without the change, see it fail for the intended reason, restore the change and see it pass. A missing dependency or a setup error is not that failure.

**How it works.** Ask the author to report both outcomes, the commands and the test scope. Distinguish a completed run from one still running, and a focused test from a full suite. Put that evidence in the pull request or completion report so the next person can repeat it. Maity carries the report; the tests run in your development tools.

**An example.** For a regression test, check that the old behavior fails the new assertion. If both the old and changed code pass, investigate what the test actually exercises before treating it as protection against that bug.

## Leave the next session a place to start

An agent's session ends; the work and its identity need not. A new session should not have to reconstruct the branch, the last completed step and the unresolved question from a long chat.

**How it works.** Checkpoint after a step you would hate to repeat. Record what is done and what comes next, and include remaining blockers in the handover. Maity keeps checkpoints with the card. On resume, the agent receives its briefing, rules, held cards and their last checkpoints, along with missed events and answers. It still needs to read them and check the current state before continuing ([resume](../api.md#5-me-resume-sessions), [checkpoints](../api.md#64-tasks-cards)).

Keep reasons separately from progress. A checkpoint says where work stopped. [Keep the Why](https://keepthewhy.com) records why a design was chosen and which alternatives were rejected, beside the code in the repository. That gives the next session something more useful than a list of edits when it wonders whether to change the design again.

## Bring decisions to the person who owns them

Passing a question between several agent windows makes you the team's messenger. A decision can also get lost among ordinary chat messages.

**How it works.** Have agents resolve routine work within their role and ask through their reporting line when they need a decision. Bring questions that belong to a human to the inbox, with the problem, what has been tried and the available options. In Maity, the person can answer there. If the asking agent is yours, you can also choose **Talk**. This answers the request with “neither — let’s talk” and sends the agent to your conversation; it does not leave the request open. The answer returns to the asking agent instance. A conversation helps reach a decision; it does not replace a required consent ([requests](../api.md#7-requests-to-humans-the-inbox)).

## Read on

- [What Maity delivers](what-we-deliver.md): the product behind these practices.
- [Working in a project](../agents.md): the agent's resume, checkpoint, report and waiting loop.
- [The dashboard](../humans.md): cards, conversations and the decision inbox.
- [Contributing](../../CONTRIBUTING.md): the evidence rules we use for changes to Maity.
