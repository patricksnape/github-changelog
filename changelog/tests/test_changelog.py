import unittest

from changelog import (
    Authorization,
    GitHubConfig,
    GithubAPI,
    PullRequest,
    Commit,
    fetch_changes,
    format_changes,
)


def commit_json(sha, author_login="someone", date="2026-01-01T00:00:00Z"):
    return {
        "sha": sha,
        "author": None if author_login is None else {"login": author_login},
        "commit": {
            "message": f"message of {sha}",
            "author": {"name": "Git Name", "date": date},
            "committer": {"date": date},
        },
    }


def pr_json(number, title, login="someone", merged=True):
    return {
        "number": number,
        "title": title,
        "user": None if login is None else {"login": login},
        "merged_at": "2026-01-01T00:00:00Z" if merged else None,
    }


class FakeAPI(GithubAPI):
    """GithubAPI that answers from a dict instead of the network."""

    responses = None
    calls = None

    def api_query(self, url, params=None):
        key = (url, tuple(sorted((params or {}).items())))
        self.calls.append(key)
        return self.responses[key]


def make_api(responses):
    api = FakeAPI(
        GitHubConfig(api_url="https://api.test", authorization=Authorization("t")),
        "owner",
        "repo",
    )
    object.__setattr__(api, "responses", responses)
    object.__setattr__(api, "calls", [])
    return api


BASE = "https://api.test/repos/owner/repo"


def compare_key(first, last, page, per_page=100):
    return (
        f"{BASE}/compare/{first}...{last}",
        (("page", str(page)), ("per_page", str(per_page))),
    )


def pulls_key(sha):
    return (f"{BASE}/commits/{sha}/pulls", (("per_page", "100"),))


FIRST = Commit("a" * 40, None, "first", "x")
LAST = Commit("b" * 40, None, "last", "x")


class CommitTests(unittest.TestCase):
    def test_null_author_falls_back_to_the_git_author_name(self):
        commit = Commit.init_from_api(commit_json("abc", author_login=None))
        self.assertEqual(commit.author, "Git Name")

    def test_linked_author_uses_the_github_login(self):
        commit = Commit.init_from_api(commit_json("abc", author_login="octocat"))
        self.assertEqual(commit.author, "octocat")


class PullRequestLookupTests(unittest.TestCase):
    def test_finds_prs_from_commits_regardless_of_merge_style(self):
        # a rebase merge: commit messages carry no PR number at all
        api = make_api(
            {
                compare_key(FIRST.sha, LAST.sha, 1): {
                    "commits": [commit_json("c1"), commit_json("c2"), commit_json("c3")]
                },
                pulls_key("c1"): [pr_json(10, "Add a thing")],
                pulls_key("c2"): [pr_json(10, "Add a thing")],  # same PR, 2nd commit
                pulls_key("c3"): [pr_json(9, "Fix a bug", login="octocat")],
            }
        )
        prs = api.get_prs_merged_between_commits(FIRST, LAST)
        self.assertEqual(
            prs,
            [
                PullRequest(9, "Fix a bug", "octocat"),
                PullRequest(10, "Add a thing", "someone"),
            ],
        )

    def test_ignores_unmerged_prs_and_handles_deleted_users(self):
        api = make_api(
            {
                compare_key(FIRST.sha, LAST.sha, 1): {"commits": [commit_json("c1")]},
                pulls_key("c1"): [
                    pr_json(1, "Closed without merging", merged=False),
                    pr_json(2, "Merged by a deleted user", login=None),
                ],
            }
        )
        self.assertEqual(
            api.get_prs_merged_between_commits(FIRST, LAST),
            [PullRequest(2, "Merged by a deleted user", "ghost")],
        )

    def test_commits_without_prs_are_ignored(self):
        api = make_api(
            {
                compare_key(FIRST.sha, LAST.sha, 1): {"commits": [commit_json("direct")]},
                pulls_key("direct"): [],
            }
        )
        self.assertEqual(api.get_prs_merged_between_commits(FIRST, LAST), [])

    def test_follows_pagination_of_the_compare_api(self):
        page1 = [commit_json(f"p1-{i}") for i in range(100)]
        page2 = [commit_json("p2-0")]
        responses = {
            compare_key(FIRST.sha, LAST.sha, 1): {"commits": page1},
            compare_key(FIRST.sha, LAST.sha, 2): {"commits": page2},
        }
        for c in page1 + page2:
            responses[pulls_key(c["sha"])] = []
        responses[pulls_key("p2-0")] = [pr_json(7, "Only on the second page")]
        api = make_api(responses)
        commits = api.get_commits_between(FIRST, LAST)
        self.assertEqual(len(commits), 101)
        self.assertEqual(
            api.get_prs_merged_between_commits(FIRST, LAST),
            [PullRequest(7, "Only on the second page", "someone")],
        )


class FetchChangesTests(unittest.TestCase):
    def tag_responses(self, name, sha):
        return {
            (f"{BASE}/git/refs/tags/{name}", ()): {
                "object": {"type": "commit", "sha": sha}
            },
            (f"{BASE}/commits/{sha}", ()): commit_json(sha),
        }

    def test_current_defaults_to_the_head_of_the_default_branch(self):
        responses = {
            (BASE, ()): {"default_branch": "main"},
            (f"{BASE}/commits", (("sha", "main"),)): [commit_json("head")],
            compare_key("old", "head", 1): {"commits": [commit_json("c1")]},
            pulls_key("c1"): [pr_json(3, "Something")],
        }
        responses.update(self.tag_responses("v1", "old"))
        api = make_api(responses)
        self.assertEqual(
            fetch_changes(api, previous_tag_name="v1"),
            [PullRequest(3, "Something", "someone")],
        )

    def test_annotated_tags_are_followed_to_their_commit(self):
        responses = {
            (f"{BASE}/git/refs/tags/v1", ()): {
                "object": {"type": "tag", "url": f"{BASE}/git/tags/tagobj"}
            },
            (f"{BASE}/git/tags/tagobj", ()): {
                "object": {"type": "commit", "sha": "real"}
            },
            (f"{BASE}/commits/real", ()): commit_json("real"),
        }
        self.assertEqual(make_api(responses).get_tag("v1").commit.sha, "real")


class FormatTests(unittest.TestCase):
    def test_restructuredtext_bullets_then_link_targets(self):
        lines = format_changes(
            "https://github.com", "owner", "repo", [PullRequest(5, "Title", "me")]
        )
        self.assertEqual(
            lines,
            [
                "- `#5`_ Title (@me)",
                ".. _#5: https://github.com/owner/repo/pull/5",
            ],
        )


if __name__ == "__main__":
    unittest.main()
