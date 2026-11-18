# github-changelog

This is a small utility that generates a changelog between two git tags from the GitHub pull requests that were merged in that range, as a ReStructuredText bullet list (ready to paste into a Sphinx `changelog.rst`).

An example of the output:

```rst
- `#1234`_ Improve test coverage for mygreatpackage.subpackage (@octocat)
- `#1233`_ Add support for Python 3 (@octocat)
.. _#1234: https://github.com/owner/repo/pull/1234
.. _#1233: https://github.com/owner/repo/pull/1233
```

## Installing

```
pip install git+https://github.com/patricksnape/github-changelog
```

(or `uvx --from git+https://github.com/patricksnape/github-changelog changelog ...` to run it without installing).

## Using

```
changelog [-h] [-s] [--github-token TOKEN] OWNER REPO [PREVIOUS] [CURRENT]
```

The `changelog` command takes a GitHub repository owner (user or organization), repository name and zero, one, or two tags to limit the set of changes to consider. If no tags are provided, the changelog will be computed between the latest tag and the head of the repository's default branch. One tag may be provided to set the base tag to compare against the head of the default branch. Two tags may be provided to specify both base tag and ending tag.

A GitHub token is required (`--github-token`, or the `GITHUB_API_TOKEN` environment variable; for example `GITHUB_API_TOKEN=$(gh auth token) changelog ...`).

### How the pull requests are found

The commits between the two tags are listed (all pages), and each commit is asked which pull requests it belongs to. This does not depend on how the pull requests were merged (merge commit, squash or rebase) or on commit message conventions, and does not use dates, so a pull request merged right before a tag is not lost. Only merged pull requests are listed, each once, sorted by number.

### Examples

```
changelog cfpb github-changelog
```

Will generate a changelog between the latest tag and the head of the default branch.

```
changelog cfpb github-changelog 1.0.0
```

Will generate a changelog between `1.0.0` and the head of the default branch.

```
changelog cfpb github-changelog 1.0.0 1.0.1
```

Will generate a changelog between `1.0.0` and `1.0.1`.

## GitHub Enterprise Support

Use the optional `--github-base-url`, `--github-api-url`, and `--github-token` arguments to connect to a GitHub Enterprise instance. For example:

```bash
changelog owner some-repo \
--github-base-url "https://github.company.com" \
--github-api-url "https://github.company.com/api/v3" \
--github-token secret-value
```

## Getting help

Please add issues to the [issue tracker](https://github.com/cfpb/wagtail-flags/issues).

## Getting involved

General instructions on _how_ to contribute can be found in [CONTRIBUTING](CONTRIBUTING.md).

## Open source licensing info
1. [TERMS](TERMS.md)
2. [LICENSE](LICENSE)
3. [CFPB Source Code Policy](https://github.com/cfpb/source-code-policy/)
