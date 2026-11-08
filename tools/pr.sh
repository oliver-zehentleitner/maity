#!/usr/bin/env bash
# Open a pull request, or edit its title and body, over GitHub's REST API: for sessions whose
# GitHub tool or GraphQL is refused (Claude Code's cloud sessions), where `gh pr create` and
# `gh pr edit` cannot work.
#
#   tools/pr.sh open --title T --body-file F [--base B] [--draft] [<branch>]
#   tools/pr.sh edit <number> [--title T] [--body-file F] [--branch B]
#
# open: POST repos/{owner}/{repo}/pulls with head <branch> (default: the checked-out branch) and
# base B (default main). It refuses unless origin has the branch at the same commit as the local
# branch, so a pull request is never opened for work that is not pushed.
# edit: PATCH repos/{owner}/{repo}/pulls/<number> with the fields given. It refuses an edit that
# names no field, and a pull request whose head is not the checked-out branch (or B) in origin's
# repository: every agent pushes as the same GitHub account, so the head ref, not the author, is
# what keeps an agent to its own pull request. A guard against mistakes, not an access control.
#
# The body always comes from a file, sent as its bytes: no shell quoting of Markdown. Both refuse
# a body with an attribution line (Co-Authored-By:, Claude-Session:, "Generated with ... Claude
# Code"): pull requests here carry none. Nothing else is sent, and nothing is added.
#
# Owner, repository and host are origin's, read from `remote.origin.url` as tools/overlap.sh
# reads them, never gh's own choice (GH_REPO, `gh repo set-default`, another logged-in host).
# On success it prints what GitHub answered: number, URL, head commit and title.
#
# Exit 0 done, 1 refused (the reason on stderr), 2 could not run (a git or gh call failed, or
# GitHub's answer was not what was asked). A run that did not reach GitHub never ends in 0.
set -uo pipefail

die() {
  echo "pr: $*" >&2
  exit 2
}

refuse() {
  echo "pr: $*" >&2
  exit 1
}

usage() {
  sed -n '7,8p' "$0" | sed 's/^# //' >&2
  exit 2
}

git() {
  command git -c core.quotePath=false "$@"
}

# JSON is built and read by Python, not by the shell: no quoting, no gh field magic (`-F`
# converts "true" and numbers), the same bytes in as out. -I: no file next to the caller runs.
py() {
  python3 -I -c "$@"
}

[ $# -ge 1 ] || usage
action=$1
shift
case $action in
  open | edit) ;;
  -h | --help) usage ;;
  *) die "unknown action '$action' (open or edit)" ;;
esac

title="" title_set=0 body_file="" base=main draft=0 branch="" number=""
while [ $# -gt 0 ]; do
  case $1 in
    --title)
      [ $# -ge 2 ] || die "--title needs a value"
      title=$2 title_set=1
      shift 2
      ;;
    --body-file)
      [ $# -ge 2 ] || die "--body-file needs a file"
      body_file=$2
      shift 2
      ;;
    --base)
      [ "$action" = open ] || die "--base is for open"
      [ $# -ge 2 ] || die "--base needs a branch"
      base=$2
      shift 2
      ;;
    --draft)
      [ "$action" = open ] || die "--draft is for open"
      draft=1
      shift
      ;;
    --branch)
      [ "$action" = edit ] || die "--branch is for edit (open takes the branch as its argument)"
      [ $# -ge 2 ] || die "--branch needs a branch"
      branch=$2
      shift 2
      ;;
    -*) die "unknown option $1" ;;
    *)
      if [ "$action" = edit ] && [ -z "$number" ]; then
        number=$1
      elif [ "$action" = open ] && [ -z "$branch" ]; then
        branch=$1
      else
        die "unexpected argument $1"
      fi
      shift
      ;;
  esac
done

# --- origin's repository and host, as tools/overlap.sh reads them -----------------------------
# The URL as configured: `git remote get-url` applies url.<base>.insteadOf, which can name a
# mirror whose path is not the repository's on GitHub.
origin=$(git config --get remote.origin.url) || die "no remote origin"
slug=${origin%/}
slug=${slug%.git}
slug=${slug//:/\/}
[[ $slug == */*/* || $slug == [!/]*/* ]] || die "cannot read an owner and a repository from origin's URL $origin"
repo_name=${slug##*/}
slug=${slug%/*}
repo_owner=${slug##*/}
[[ $repo_owner =~ ^[A-Za-z0-9._-]+$ && $repo_name =~ ^[A-Za-z0-9._-]+$ ]] \
  || die "cannot read an owner and a repository from origin's URL $origin"
case $origin in
  file://*) authority="" ;;
  *://*)
    authority=${origin#*://}
    authority=${authority%%/*}
    ;;
  */*:* | *:*) authority=${origin%%:*} ;;
  *) authority="" ;;
esac
[[ $origin == *://* || $authority != */* ]] || authority=""
authority=${authority##*@}
case $authority in
  \[*) repo_host=${authority%%]*}] ;;
  *) repo_host=${authority%%:*} ;;
esac
repo_host=${repo_host,,}
# A host on the loopback is a proxy in front of github.com (cloud sessions fetch through one).
if [[ $repo_host == localhost || $repo_host == "[::1]" || $repo_host =~ ^127(\.[0-9]{1,3}){3}$ ]]; then
  repo_host=github.com
fi
[[ $repo_host =~ ^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$ ]] \
  || die "cannot read a host from origin's URL $origin"
repo="$repo_owner/$repo_name"

# --- the body ---------------------------------------------------------------------------------
if [ -n "$body_file" ]; then
  [ -f "$body_file" ] && [ -r "$body_file" ] || die "cannot read the body file $body_file"
  # An attribution line, in any case: Co-Authored-By: or Claude-Session: at a line's start (after
  # spaces), or "Generated with" followed by Claude Code on the line.
  if grep -Eiq '^[[:space:]]*(co-authored-by|claude-session):|generated with.*claude code' "$body_file"; then
    refuse "the body has an attribution line (Co-Authored-By, Claude-Session or Generated with ... Claude Code); pull requests here carry none"
  fi
fi

# The request's JSON from the arguments: py reads the body file itself, as bytes decoded UTF-8.
request_json() {
  py '
import json, sys
fields = {}
args = sys.argv[1:]
for key, value in zip(args[::2], args[1::2]):
    if key == "body":
        with open(value, encoding="utf-8") as f:
            fields["body"] = f.read()
    elif key == "draft":
        fields["draft"] = value == "1"
    else:
        fields[key] = value
print(json.dumps(fields))
' "$@"
}

# One field of GitHub's JSON answer on stdin, by a dotted path ("head.ref"); empty when absent.
field() {
  py '
import json, sys
value = json.load(sys.stdin)
for part in sys.argv[1].split("."):
    value = value.get(part) if isinstance(value, dict) else None
print("" if value is None else value)
' "$1"
}

report() {
  local answer=$1
  printf '#%s %s\n  head %s\n  title %s\n' \
    "$(field number <<<"$answer")" "$(field html_url <<<"$answer")" \
    "$(field head.sha <<<"$answer")" "$(field title <<<"$answer")"
}

if [ "$action" = open ]; then
  [ "$title_set" = 1 ] && [ -n "$title" ] || refuse "open needs --title"
  [ -n "$body_file" ] || refuse "open needs --body-file"
  if [ -z "$branch" ]; then
    branch=$(git symbolic-ref --quiet --short HEAD) || refuse "no branch checked out; name it"
  fi
  [ "$branch" != "$base" ] || refuse "the branch is the base ($base)"
  local_head=$(git rev-parse --verify --quiet "refs/heads/$branch^{commit}") \
    || refuse "no local branch $branch"
  remote=$(git ls-remote origin "refs/heads/$branch") || die "cannot read origin's branches (git ls-remote)"
  remote_head=${remote%%[[:space:]]*}
  [ -n "$remote_head" ] || refuse "origin has no branch $branch: push it first"
  [ "$remote_head" = "$local_head" ] \
    || refuse "origin's $branch is at ${remote_head:0:12}, the local one at ${local_head:0:12}: push first"
  args=(title "$title" head "$branch" base "$base" body "$body_file")
  [ "$draft" = 1 ] && args+=(draft 1)
  payload=$(request_json "${args[@]}") || die "cannot build the request"
  answer=$(gh api --hostname "$repo_host" -X POST "repos/$repo/pulls" --input - <<<"$payload") \
    || die "opening the pull request on $repo ($repo_host) failed (gh api)"
  [ "$(field head.sha <<<"$answer")" = "$local_head" ] \
    || die "GitHub answered with another head than $local_head: $(field html_url <<<"$answer")"
  report "$answer"
  exit 0
fi

# --- edit -------------------------------------------------------------------------------------
[[ $number =~ ^[1-9][0-9]*$ ]] || refuse "edit needs a pull request number"
[ "$title_set" = 1 ] || [ -n "$body_file" ] || refuse "edit names no field: give --title or --body-file"
[ "$title_set" = 0 ] || [ -n "$title" ] || refuse "the title cannot be empty"
if [ -z "$branch" ]; then
  branch=$(git symbolic-ref --quiet --short HEAD) || refuse "no branch checked out; give --branch"
fi
current=$(gh api --hostname "$repo_host" "repos/$repo/pulls/$number") \
  || die "reading pull request #$number of $repo ($repo_host) failed (gh api)"
head_ref=$(field head.ref <<<"$current")
head_repo=$(field head.repo.full_name <<<"$current")
[ "$head_repo" = "$repo" ] || refuse "#$number's head is in ${head_repo:-a deleted repository}, not $repo"
[ "$head_ref" = "$branch" ] || refuse "#$number's head is $head_ref, not $branch: edit only your own pull request"
args=()
[ "$title_set" = 1 ] && args+=(title "$title")
[ -n "$body_file" ] && args+=(body "$body_file")
payload=$(request_json "${args[@]}") || die "cannot build the request"
answer=$(gh api --hostname "$repo_host" -X PATCH "repos/$repo/pulls/$number" --input - <<<"$payload") \
  || die "editing pull request #$number of $repo ($repo_host) failed (gh api)"
[ "$(field number <<<"$answer")" = "$number" ] || die "GitHub answered for another pull request"
report "$answer"
