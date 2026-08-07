# On-call handover

Creates a weekly Notion handover page containing high-urgency PagerDuty
incidents and outstanding actions from the previous handover.

## What it does

For the current or upcoming Monday, the command:

1. Fetches high-urgency PagerDuty incidents from the previous Monday at 12:00
   through the handover Monday at 12:00.
2. Optionally resolves the scheduled primary on-call person to a Notion user.
3. Creates a Notion page with its title, date, creator, and optional primary.
4. Applies the configured Notion template and validates its expected headings.
5. Upserts each incident into the shared high-urgency incidents data source and
   inserts a linked database under **High Urgency Paging** with **By duration**
   and **Chronological** views for that week (skipped if the page already has
   a linked view).
6. Replaces **Previous actions** with content from both **Previous actions** and
   **Actions** on the latest prior handover.

If a handover page already exists for that Monday `Date`, the command updates it
instead of creating another page. Template application and page properties are
left alone on update; incident rows refresh via upsert and the existing linked
view reflects them automatically.

PagerDuty access is read-only. Notion access creates and populates the new page,
writes incident rows, and removes empty placeholders from that page.

## Setup

Python 3.11 or newer is required.

1. Create and activate a virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install the package (and test extras if you want to run tests):

```bash
pip install -e .
# or: pip install -e '.[test]'
```

3. Create a local env file from the checked-in example:

```bash
cp .env.example .env
```

4. Fill in the two API tokens in `.env` (see [Getting API tokens](#getting-api-tokens)):

- `PAGERDUTY_API_TOKEN`: classic PagerDuty user token.
- `NOTION_API_TOKEN`: Notion personal access token.

Everything else in `.env.example` is already filled with the non-sensitive
workspace configuration.

### Other configuration

These values are already set in `.env.example` and usually do not need changing:

- `PAGERDUTY_PRIMARY_SCHEDULE_ID`: schedule used for **Now Primary**.
- `NOTION_DATA_SOURCE_ID`: handover data source used to create pages and find
  the previous handover.
- `NOTION_INCIDENTS_DATA_SOURCE_ID`: shared high-urgency incidents data source
  used for incident rows and per-page linked views.
- `NOTION_TEMPLATE_ID`: template applied to the new page.
- `NOTION_TITLE_PROPERTY`: title property, default `Title`.
- `NOTION_TIMEZONE`: IANA timezone, default `Europe/London`.
- `MENTION_NOW_PRIMARY`: enables primary-user resolution when set to `1`,
  `true`, or `yes`; default `false`.

During development, point `NOTION_DATA_SOURCE_ID` and
`NOTION_INCIDENTS_DATA_SOURCE_ID` at the test databases (Oncall handover test /
High urgency events test) before switching back to production ids.

API tokens belong only in `.env`. Template headings are defined in
`on_call_handover/config.py` as part of the code-level template contract:

- `🚨 High Urgency Paging`
- `🌝 Previous actions`
- `🚀 Actions`

The target template must contain all three as exact heading text. Template
materialization is asynchronous, so the command polls for up to 30 seconds and
reports any missing headings.

## Run

With the virtualenv activated:

```bash
on-call-handover
```

Or without activating it:

```bash
.venv/bin/on-call-handover
```

These entry points are equivalent:

```bash
python -m on_call_handover
python main.py
```

The command returns exit code `0` on success and `1` for invalid configuration,
API failures, template timeouts, or workflow errors.

## Notion schema

### Handover pages

The handover data source must contain:

- `Title` as a title property, or the name configured by
  `NOTION_TITLE_PROPERTY`.
- `Date` as a date property.
- `Created By` as a people property.
- `Now Primary` as a people property when primary mentions are enabled.

People properties on existing handover pages may be used as a fallback when
resolving a primary user by email.

The template is applied after page creation using `erase_content=true`. This is
intentional: applying it in the create request can produce a blank page in the
current workspace.

Do not put the high-urgency linked view in the template. Each run creates a view
with absolute `Created` bounds for that Monday–Monday window so historical pages
keep the correct week when reopened later. After inserting the linked database,
the script removes the template **High Urgency Paging** heading and titles the
linked database instead, with a blank paragraph above it for spacing. After inserting the linked database,
the script removes the template **High Urgency Paging** heading and uses the
linked database title instead, so the section is not labeled twice.

### High-urgency incidents

The incidents data source (`NOTION_INCIDENTS_DATA_SOURCE_ID`) must contain:

- `Name` (title)
- `URL` (url)
- `Created` (date with time)
- `Duration (minutes)` (number) — sort key
- `Duration` (rich text) — display string such as `1h 12m`
- `Status` (status with `Open` / `Resolved`)
- `Incident ID` (rich text) — used to upsert on re-runs

Share both databases with the Notion integration used by `NOTION_API_TOKEN`.

## Primary-user mapping

Primary resolution is skipped entirely unless `MENTION_NOW_PRIMARY=true`.
When enabled, the command:

1. Gets the level-one PagerDuty on-call user at Monday 12:00 local time.
2. Looks in `user_map.json` by PagerDuty email, then by PagerDuty name.
3. Falls back to an exact email match among people found on existing handovers.

Notion's workspace-wide `/v1/users` endpoint is not called because it is not
available to the current token.

The map has this shape:

```json
{
  "by_pagerduty_email": {
    "person@example.com": "notion-user-id"
  },
  "by_pagerduty_name": {
    "example person": "notion-user-id"
  }
}
```

Email and name keys are normalized to lowercase. `user_map.json` is the
checked-in, static mapping used by this project.

## Incident formatting

Incidents are fetched for the Monday–Monday alert window and upserted into the
shared incidents data source. Under **High Urgency Paging**, the page gets a
linked table views that:

- Filter `Created` to the same alert window
- Default to **By duration** (`Duration (minutes)` descending), with a second
  **Chronological** view (`Created` descending) on the same linked database
- Show only `Name`, `Created`, and `Duration` (other properties remain on the
  incident page), with a wide wrapping Name column

Long titles are limited to 60 characters for table readability. If no incidents
occurred, the page contains a single “No high-urgency incidents in the past
week” bullet instead of an empty linked view.

## Action carry-forward

The latest prior page is selected by `Date` descending, excluding the page just
created. Blocks under **Previous actions** are copied first, followed by blocks
under **Actions**. Both groups are inserted under **Previous actions** on the
new page.

Supported block types are paragraphs, to-dos, bulleted and numbered items,
toggles, quotes, and callouts. Text formatting, links, supported mentions,
to-do state, and nested children are preserved. Unsupported block types are
skipped with a warning.

## Verify

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

The tests cover configuration, incident formatting, PagerDuty pagination,
Notion block helpers, and the main workflow without making external API calls.

## Project structure

- `on_call_handover/config.py`: typed environment configuration and template
  contract.
- `on_call_handover/pagerduty.py`: PagerDuty API client.
- `on_call_handover/notion.py`: Notion API client.
- `on_call_handover/blocks.py`: Notion block transformations.
- `on_call_handover/users.py`: local PagerDuty-to-Notion mappings.
- `on_call_handover/time_utils.py`: handover date and alert-window calculations.
- `on_call_handover/service.py`: workflow orchestration.
- `on_call_handover/cli.py`: logging and process exit codes.
- `main.py`: compatibility entry point.
- `tests/`: unit and workflow tests.

## Current operational constraints

- Re-running the command for the same Monday updates that page: incident rows
  are upserted, an existing High Urgency linked view is left in place, and
  **Previous actions** is replaced from the prior handover.
- A failure after page creation can leave a partially populated page.
- Heading text and Notion property names must match the documented contract.
- Transient API errors are not retried automatically.
- The command does not modify PagerDuty incidents or schedules.

## Appendix: Getting API tokens

### PagerDuty

Create a classic user API key from your PagerDuty profile:

1. Click your user icon in the top-right corner.
2. Open **My Profile**.
3. Go to the **User Settings** tab.
4. In the **API Access** section, click **+ Create API User Key**.
5. Copy the key into `PAGERDUTY_API_TOKEN` in `.env`.

Treat this like a password: it can access whatever your PagerDuty user can
access.

### Notion

Create a personal access token from the Notion developers portal:

1. Open the [Notion developers portal](https://app.notion.com/developers).
2. Go to the **Personal access tokens** tab.
3. Click **+ New token**.
4. Grant the token access to the handover database, its template, and the
   high-urgency incidents database.
5. Copy the token into `NOTION_API_TOKEN` in `.env`.

The token only works for pages and databases you explicitly share with it.
