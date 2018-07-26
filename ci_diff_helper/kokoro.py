# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Set of utilities for dealing with Kokoro (Google's internal Jenkins).

This module provides a custom configuration type
:class:`Kokoro` for the `Kokoro`_ CI system.

.. _Kokoro: https://www.cloudbees.com/sites/default/files/2016-jenkins-world-jenkins_inside_google.pdf

This module uses a selection of environment variables to detect the state of
Kokoro configuration. See :mod:`~ci_diff_helper.environment_vars` for more
details.

:class:`Kokoro` Configuration Type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When running in Kokoro, you can automatically detect your
current environment and get the configuration object:

.. testsetup:: auto-detect

  import os
  os.environ = {
      'KOKORO_ENV_VAR': 'some-value',
  }

.. doctest:: auto-detect

  >>> import ci_diff_helper
  >>> config = ci_diff_helper.get_config()
  >>> config
  <Kokoro (active=True)>

To use the :class:`Kokoro` configuration type directly:

.. testsetup:: kokoro-ci-push

  import os
  os.environ = {
      'KOKORO_ENV_VAR': 'some-value',
      'GERRIT_BRANCH': 'master',
      'GERRIT_CHANGE_URL': 'https://go-review.googlesource.com/94839',
  }
  import ci_diff_helper

.. doctest:: kokoro-ci-push

  >>> config = ci_diff_helper.Kokoro()
  >>> config
  <Kokoro (active=True)>
  >>> config.branch
  'master'
  >>> config.provider
  <KokoroRepoProvider.gerrit: 'gerrit'>

During a pull request build, we can determine information about
the current PR being built:

.. testsetup:: kokoro-ci-pr

  import os
  os.environ = {
      'KOKORO_ENV_VAR': 'some-value',
      'KOKORO_GITHUB_PULL_REQUEST_NUMBER': '23',
      'KOKORO_GITHUB_PULL_REQUEST_URL': (
          'https://github.com/organization/repository/pull/23'),
  }
  import ci_diff_helper
  from ci_diff_helper import _github

  def mock_pr_info(slug, pr_id):
      assert slug == 'organization/repository'
      assert pr_id == 23
      payload = {
          'base': {
              'sha': '7450ebe1a2133442098faa07f3c2c08b612d75f5',
          },
      }
      return payload

  _github.pr_info = mock_pr_info

.. doctest:: kokoro-ci-pr

  >>> config = ci_diff_helper.Kokoro()
  >>> config
  <Kokoro (active=True)>
  >>> config.in_pr
  True
  >>> config.pr
  23
  >>> config.base
  '7450ebe1a2133442098faa07f3c2c08b612d75f5'
"""

import os
import re

import enum

from ci_diff_helper import _config_base
from ci_diff_helper import _github
from ci_diff_helper import _utils
from ci_diff_helper import environment_vars as env


_REPO_URL_TEMPLATE = (
    'Kokoro build does not have a repo URL set (via {} or {})')
_GITHUB_HOST = 'github.com'
_GITHUB_PREFIX = 'https://{}/'.format(_GITHUB_HOST)


def _in_ci():
    env_keys = os.environ.keys()
    return any((key.startswith('KOKORO_') for key in env_keys))


def _ci_branch(provider):
    if provider != KokoroRepoProvider.gerrit:
        return None
    # Gerrit does not have branch set on merge commits.
    return os.environ.get(env.KOKORO_GERRIT_BRANCH)


def _kokoro_ci_pr():
    """Get the current Kokoro pull request (if any).

    Returns:
        Optional[int]: The current pull request ID.
    """
    try:
        return int(os.getenv(env.KOKORO_GITHUB_PULL_REQUEST_NUMBER, ''))
    except ValueError:
        pass
    try:
        return int(os.getenv(env.KOKORO_GERRIT_CHANGE_NUMBER, ''))
    except ValueError:
        return None


def _repo_url():
    """Get the repository URL for the current build.

    Returns:
        Optional[str]: The repository URL for the current build.
    """
    try:
        pr_url = os.environ[env.KOKORO_GITHUB_PULL_REQUEST_URL]
        return re.sub(r'/pull/[0-9]+', '', pr_url)
    except KeyError:
        pass

    try:
        commit_url = os.environ[env.KOKORO_GITHUB_COMMIT_URL]
        return re.sub(r'/commit/.*', '', commit_url)
    except KeyError:
        return None


def _provider_slug(repo_url):
    """Get the code hosting provider for the current Kokoro build.

    Args:
        repo_url (str): The URL of a code hosting repository.

    Returns:
        Tuple[KokoroRepoProvider, str]: Pair of the code hosting provider
            for the current Kokoro build and the repository slug.

    Raises:
        ValueError: If we couldn't determine the provider.
    """
    env_keys = os.environ.keys()
    if (env.KOKORO_GERRIT_BRANCH in env_keys
            or env.KOKORO_GOB_COMMIT in env_keys):
        return KokoroRepoProvider.gerrit, None

    if repo_url and _GITHUB_HOST in repo_url:
        if repo_url.startswith(_GITHUB_PREFIX):
            _, slug = repo_url.split(_GITHUB_PREFIX, 1)
            return KokoroRepoProvider.github, slug
        else:
            raise ValueError('Repository URL contained host',
                             _GITHUB_HOST,
                             'but did not begin as expected',
                             'expected prefix', _GITHUB_PREFIX)

    raise ValueError('Could not detect Kokoro provider.')


# pylint: disable=too-few-public-methods
class KokoroRepoProvider(enum.Enum):
    """Enum representing all possible Kokoro repo providers."""
    github = 'github'
    gerrit = 'gerrit'
# pylint: enable=too-few-public-methods


class Kokoro(_config_base.Config):
    """Represent Kokoro state and cache return values."""

    # Default instance attributes.
    _base = _utils.UNSET
    _pr = _utils.UNSET
    _pr_info_cached = _utils.UNSET
    _provider = _utils.UNSET
    _repo_url = _utils.UNSET
    _slug = _utils.UNSET
    # Class attributes.
    _branch_env_var = env.KOKORO_GERRIT_BRANCH

    @property
    def active(self):
        """bool: Indicates if currently running in the target CI system."""
        if self._active is _utils.UNSET:
            self._active = _in_ci()
        return self._active

    @property
    def branch(self):
        """bool: Indicates the current branch in the target CI system.

        This may indicate the active branch or the base branch of a
        pull request.
        """
        if self._branch is _utils.UNSET:
            self._branch = _ci_branch(self.provider)
        return self._branch

    @property
    def pr(self):
        """int: The current Kokoro pull request (if any).

        If there is no active pull request, returns :data:`None`.
        """
        if self._pr is _utils.UNSET:
            self._pr = _kokoro_ci_pr()
        return self._pr

    @property
    def in_pr(self):
        """bool: Indicates if currently running in Kokoro pull request.

        This uses the ``GITHUB_PULL_REQUEST_NUMBER`` or
        ``GERRIT_CHANGE_NUMBER`` environment variable to check if currently
        in a pull request.
        """
        return self.pr is not None

    @property
    def _pr_info(self):
        """dict: The information for the current pull request.

        This information is retrieved from the GitHub API and cached.
        It is non-public, but a ``@property`` is used for the caching.

        .. warning::

            This property is only meant to be used in a pull request
            from a GitHub repository.
        """
        if self._pr_info_cached is not _utils.UNSET:
            return self._pr_info_cached

        current_pr = self.pr
        if current_pr is None:
            self._pr_info_cached = {}
        elif self.provider is KokoroRepoProvider.github:
            self._pr_info_cached = _github.pr_info(self.slug, current_pr)
        else:
            raise NotImplementedError(
                'GitHub is only supported way to retrieve PR info')

        return self._pr_info_cached

    @property
    def repo_url(self):
        """str: The URL of the current repository being built.

        For example: ``https://github.com/{organization}/{repository}``
        """
        if self._repo_url is _utils.UNSET:
            self._repo_url = _repo_url()
        return self._repo_url

    @property
    def provider(self):
        """str: The code hosting provider for the current CircleCI build."""
        if self._provider is _utils.UNSET:
            # NOTE: One **could** check here that _slug isn't already set,
            #       but that would be over-protective, since the only
            #       way it could be set also sets _provider.
            self._provider, self._slug = _provider_slug(self.repo_url)
        return self._provider

    @property
    def slug(self):
        """str: The current slug in the CircleCI build.

        Of the form ``{organization}/{repository}``.
        """
        if self._slug is _utils.UNSET:
            # NOTE: One **could** check here that _provider isn't already set,
            #       but that would be over-protective, since the only
            #       way it could be set also sets _slug.
            self._provider, self._slug = _provider_slug(self.repo_url)
        return self._slug

    @property
    def base(self):
        """str: The ``git`` object that current build is changed against.

        The ``git`` object can be any of a branch name, tag, a commit SHA
        or a special reference.

        .. warning::

            This property will currently only work in a build for a
            pull request from a GitHub repository.
        """
        if self._base is not _utils.UNSET:
            return self._base

        # Gerrit PRs always only include a single commit.
        if self.provider == KokoroRepoProvider.gerrit:
            self._base = 'HEAD~1'
            return self._base

        if self.in_pr:
            pr_info = self._pr_info
            try:
                self._base = pr_info['base']['sha']
            except KeyError:
                raise KeyError(
                    'Missing key in the GitHub API payload',
                    'expected base->sha',
                    pr_info, self.slug, self.pr)
        else:
            raise NotImplementedError(
                'Diff base currently only supported in a PR from GitHub')

        return self._base
