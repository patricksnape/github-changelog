# -*- coding: utf-8 -*-
"""
This is a script to determine which PRs have been merges since the last
release, or between two releases on the same branch.
"""
import argparse
import os
from dataclasses import dataclass
from datetime import datetime
from operator import attrgetter
from typing import Any, Dict, List, Optional

import requests

PUBLIC_GITHUB_URL = "https://github.com"
PUBLIC_GITHUB_API_URL = "https://api.github.com"


@dataclass(frozen=True)
class Authorization:
    token: str

    @property
    def token_auth(self) -> Dict[str, str]:
        return {"Authorization": f"token {self.token}"}

    @property
    def bearer_auth(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@dataclass(frozen=True)
class GitHubConfig:
    api_url: str
    authorization: Authorization


@dataclass(frozen=True)
class Commit:
    sha: str
    datetime: datetime
    message: str
    author: str

    @classmethod
    def init_from_api(cls, commit_json: Dict[str, Any]) -> "Commit":
        datetime_str = commit_json["commit"]["author"]["date"]
        return Commit(
            sha=commit_json["sha"],
            datetime=parse_datetime_string(datetime_str),
            message=commit_json["commit"]["message"],
            author=commit_json["author"]["login"],
        )


@dataclass(frozen=True)
class Tag:
    name: str
    commit: Commit


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    author: str


@dataclass(frozen=True)
class GithubAPI:
    config: GitHubConfig
    owner: str
    repo: str

    @property
    def repo_url(self) -> str:
        return f"{self.config.api_url}/repos/{self.owner}/{self.repo}"

    @property
    def commits_url(self) -> str:
        return f"{self.repo_url}/commits"

    @property
    def tags_url(self) -> str:
        return f"{self.repo_url}/tags"

    def get_commit_url(self, sha: str) -> str:
        return f"{self.commits_url}/{sha}"

    def tag_ref_url(self, tag: str) -> str:
        return f"{self.repo_url}/git/refs/tags/{tag}"

    def compare_commits_url(self, first_commit: Commit, last_commit: Commit) -> str:
        return f"{self.repo_url}/compare/{first_commit.sha}...{last_commit.sha}"

    def graphql_query(self, query: str) -> Dict[str, Any]:
        request = requests.post(
            f"{self.config.api_url}/graphql",
            json={"query": query},
            headers=self.config.authorization.bearer_auth,
        )
        if request.status_code == 200:
            return request.json()
        else:
            raise GitHubError(
                f"Query failed to run by returning code of {request.status_code}\n\n{query}"
            )

    def api_query(self, url: str, params: Optional[Dict[str, str]] = None) -> Any:
        request = requests.get(
            url, params=params, headers=self.config.authorization.token_auth
        )
        if request.status_code == 200:
            return request.json()
        else:
            raise GitHubError(
                f"Query failed to run by returning code of {request.status_code}\n\n{url}"
            )

    def get_tag(self, name: str) -> Tag:
        """ Get the commit sha for a given git tag """
        tag_url = self.tag_ref_url(name)
        tag_json = {}
        while "object" not in tag_json or tag_json["object"]["type"] != "commit":
            tag_json = self.api_query(tag_url)

            # If we're given a tag object we have to look up the commit
            if tag_json["object"]["type"] == "tag":
                tag_url = tag_json["object"]["url"]

        commit_json = self.api_query(self.get_commit_url(tag_json["object"]["sha"]))
        return Tag(name, Commit.init_from_api(commit_json))

    def get_last_commit(self, branch: str = "master") -> Commit:
        """ Get the last commit sha for the given repo and branch """
        commits_json: List[Dict[str, Any]] = self.api_query(
            self.commits_url, params={"sha": branch}
        )
        # 0 contains the latest commit
        return Commit.init_from_api(commits_json[0])

    def get_latest_tag(self) -> Tag:
        """ Get the last tag for the given repo """
        tags_json: List[Dict[str, Any]] = self.api_query(self.tags_url)
        # 0 contains the latest tag
        return self.get_tag(tags_json[0]["name"])

    def get_commits_between(
        self, first_commit: Commit, last_commit: Commit
    ) -> List[Commit]:
        """ Get a list of commits between two commits """
        commits_json = self.api_query(
            self.compare_commits_url(first_commit, last_commit)
        )

        if "commits" not in commits_json:
            raise GitHubError(
                f"Commits not found between {first_commit} and {last_commit}."
            )

        return [Commit.init_from_api(c) for c in commits_json["commits"]]

    def get_prs_merged_between_commits(
        self, first_commit: Commit, last_commit: Commit
    ) -> List[PullRequest]:
        from_date = first_commit.datetime.isoformat()
        to_date = last_commit.datetime.isoformat()
        merged_query = f"repo:{self.owner}/{self.repo} is:pr is:merged created:{from_date}..{to_date}"
        graphql_search = (
            """
            {
              search(first: 100, query: "%s", type: ISSUE) {
                nodes {
                  ... on PullRequest {
                    title
                    number
                    author { login }
                  }
                }
              }
            }
            """
            % merged_query
        )
        pr_json_list = self.graphql_query(graphql_search)
        return sorted(
            [
                PullRequest(
                    number=pr["number"], title=pr["title"], author=pr["author"]["login"]
                )
                for pr in pr_json_list["data"]["search"].get("nodes", [])
            ],
            key=attrgetter("number"),
        )


class GitHubError(Exception):
    pass


def parse_datetime_string(datetime_str: str):
    return datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))


def fetch_changes(
    github_api: GithubAPI,
    previous_tag_name: Optional[str] = None,
    current_tag_name: Optional[str] = None,
    branch: str = "master",
):
    if previous_tag_name is None:
        previous_tag_name = github_api.get_latest_tag()
    previous_tag = github_api.get_tag(previous_tag_name)

    if current_tag_name is not None:
        current_tag = github_api.get_tag(current_tag_name)
        current_commit = current_tag.commit
    else:
        current_commit = github_api.get_last_commit(branch=branch)

    return github_api.get_prs_merged_between_commits(
        first_commit=previous_tag.commit, last_commit=current_commit
    )


def format_changes(
    base_url: str, owner: str, repo: str, prs: List[PullRequest]
) -> List[str]:
    """ Format the list of PRs in ReStructuredText"""
    bullet_list = []
    url_list = []
    for pr in prs:
        bullet_list.append(f"- `#{pr.number}`_ {pr.title} (@{pr.author})")
        url_list.append(f".. _#{pr.number}: {base_url}/{owner}/{repo}/pull/{pr.number}")

    return bullet_list + url_list


def generate_changelog(
    owner,
    repo,
    previous_tag=None,
    current_tag=None,
    single_line=False,
    github_base_url=None,
    github_api_url=None,
    github_token=None,
):
    github_config = GitHubConfig(
        api_url=github_api_url,
        authorization=Authorization(github_token),
    )
    github_api = GithubAPI(github_config, owner, repo)

    prs = fetch_changes(
        github_api, previous_tag_name=previous_tag, current_tag_name=current_tag
    )
    lines = format_changes(github_base_url, owner, repo, prs)

    separator = "\\n" if single_line else "\n"
    return separator.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a CHANGELOG between two git tags based on GitHub"
        "Pull Request merge commit messages"
    )
    parser.add_argument("owner", metavar="OWNER", help="owner of the repo on GitHub")
    parser.add_argument("repo", metavar="REPO", help="name of the repo on GitHub")
    parser.add_argument(
        "previous_tag",
        metavar="PREVIOUS",
        nargs="?",
        help="previous release tag (defaults to last tag)",
    )
    parser.add_argument(
        "current_tag",
        metavar="CURRENT",
        nargs="?",
        help="current release tag (defaults to HEAD)",
    )
    parser.add_argument(
        "-s",
        "--single-line",
        action="store_true",
        help="output as single line joined by \\n characters",
    )
    parser.add_argument(
        "--github-base-url",
        type=str,
        default=PUBLIC_GITHUB_URL,
        help="Override if you are using GitHub Enterprise. e.g. https://github.my-company.com",
    )
    parser.add_argument(
        "--github-api-url",
        type=str,
        default=PUBLIC_GITHUB_API_URL,
        help="Override if you are using GitHub Enterprise. e.g. https://github.my-company.com/api/v3",
    )
    parser.add_argument(
        "--github-token",
        type=str,
        default=os.environ.get("GITHUB_API_TOKEN"),
        help="GitHub oauth token to auth your Github requests with",
    )

    args = parser.parse_args()

    changelog = generate_changelog(**vars(args))
    print(changelog)


if __name__ == "__main__":
    main()
