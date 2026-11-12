# Visible conversation transcript

Captured during the ChatGPT Work session on 12 November 2026 IST. These are the actual user request and visible assistant progress messages through final packaging preparation. Internal reasoning and tool payloads are not included. Tool payloads included private challenge-chat extracts, which are deliberately excluded to honour the rule against committing the data. This is a partial session capture, not a fabricated full export. Add later AI conversations as they happen.

## User

I Applied for this intern and got this mail to do a task I have justa day left and didn't started it so help me do it with the most perfect way it can
here is the mail ::

> Hi,
>
> Thank you for registering for the Xpert Winter Internship. The build challenge is now open, and it’s how we’ll choose our interns.
>
> The challenge: https://goals.xpert.chat/w/intern
>
> We’re building Xpert, a personal assistant that lives on WhatsApp. Before an assistant can help anyone, it has to understand their life: who the people around them are, what they care about, and what’s still open. Your task is to build that first step. From a few weeks of one person’s WhatsApp, work out their people, their goals and their open tasks, and decide where an assistant should step in and where it should stay out.
>
> Everything is on the page:
>
> the full brief and how we score it
> a starter kit, including a checker that scores your work the way we will
> the data: two weeks of chats, with answers to practise on
> a place to ask questions, and the answers everyone gets
> the submit form
>
> Key dates
>
> 12 November, 23:59 IST: submit your GitHub repo on the page
> From 16 November: 45-minute calls with shortlisted candidates, to go through your code and approach
> After the calls: final offers
>
> When you ask a question or submit, please use the same email you registered with, so we can match it to you.
>
> Using AI tools is expected. We want to see how you think and how you work with them.
>
> Good luck! We’re looking forward to what you build.
>
> Sharad Lunia

the website link of the assessment and I will attach the website link refer here and I'll add the zip files too "https://goals.xpert.chat/w/intern"

Attachments: `xpert-cold-start.zip`, `xpert-cold-start-starter.zip`.

## Assistant

I’ll read the full brief and inspect both ZIP files, then build and test the solution against their checker. I’ll also prepare the README and submission steps so you can explain the approach in the interview.

## Assistant

The brief puts most of the weight on finding real tasks and tracking whether they were completed. The hidden data also changes every name, so the solution must infer relationships from the chats rather than memorise the practice answers.

The deadline is **12 November, 11:59 PM IST**. I’m building a pipeline that follows those constraints and can be evaluated with the supplied checker.

## Assistant

The practice set has 4,502 messages across 138 chats. Its answer key contains duplicate tasks and marks some tasks done without citing a closing message, so I’ll keep the supplied checker unchanged and document those limits.

No model API key is configured here. I can test the code and its zero-cost mode now, but the model-assisted version will still need a live API run before submission.

## Assistant

The core code now keeps stable person IDs, uses the supplied relationships as anchors, and checks later messages for task completion. It also requires a closing message before marking a task done.

I’m adding the model batches, response cache, and correction support next, then I’ll run the checker and failure tests.

## Assistant

The zero-cost version scores **21.9/56** on the practice set, compared with the published model baseline of **17.5/56**. All 21 tests currently pass, including tests for the API request flow, caching, renamed IDs, and false completion handling.

The model-assisted version is implemented but still unbenchmarked. I’m finishing the evaluation command, write-up, and submission package, with that distinction clearly recorded.

## Assistant

All 24 tests now pass, including a synthetic 20,000-message run and a full API-flow test. I also verified that the supplied checker and schema are unchanged.

The package includes the code, measured results, write-up, AI collaboration log, and interview notes. I’m doing the final clean-folder check and ensuring the ZIP excludes the private chat data.
