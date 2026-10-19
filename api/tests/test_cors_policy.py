"""cors_policy table tests (ADR 0002 section 7). Pure function, no app."""

import re

import pytest

from app.cors import CorsPolicy, cors_policy

SITE = "hike-prep-abc"
OTHER = "other-project-xyz"
PREVIEW = f"https://{SITE}--pr-7-a1b2c3d4.web.app"


def allowed(policy: CorsPolicy, origin: str) -> bool:
    """Mirror Starlette: exact match, or fullmatch of the regex."""
    if origin in policy.allow_origins:
        return True
    regex = policy.allow_origin_regex
    return regex is not None and re.fullmatch(regex, origin) is not None


@pytest.fixture
def prod() -> CorsPolicy:
    return cors_policy([], SITE)


@pytest.mark.parametrize(
    "origin",
    [
        f"https://{SITE}.web.app",
        f"https://{SITE}.firebaseapp.com",
        PREVIEW,
        f"https://{SITE}--pr-12-abc123.web.app",
        f"https://{SITE}--pr-1-0.web.app",
    ],
)
def test_production_policy_accepts(prod: CorsPolicy, origin: str) -> None:
    assert allowed(prod, origin)


@pytest.mark.parametrize(
    "origin",
    [
        f"https://{SITE}.web.app.evil.com",
        f"https://evil{SITE}.web.app",
        f"https://x-{SITE}--pr-1-abc123.web.app",
        f"http://{SITE}.web.app",
        f"https://{SITE}.web.app:8443",
        f"https://{SITE}.web.app/",
        f"https://{SITE}--pr-1-abc123.firebaseapp.com",
        f"https://{SITE}--feature-abc123.web.app",
        f"https://{SITE}--pr-1-abc123.web.app.evil.com",
        f"https://{SITE}--pr-1-ABC123.web.app",
        f"https://{SITE}--pr-1-abc123.web.app\n",
        f"https://{SITE}--pr-.web.app",
        f"https://{SITE}--pr-x-abc123.web.app",
        f"https://{SITE}--pr-1-.web.app",
        f"http://{SITE}--pr-1-abc123.web.app",
        f"https://{SITE}--pr-1-abc123.web.app:8443",
        f"https://{SITE}-.web.app",
        "null",
        "",
        "*",
        "http://localhost:5173",
        f"https://{OTHER}--pr-1-abc123.web.app",
        f"https://{OTHER}.web.app",
        f"https://{OTHER}.firebaseapp.com",
    ],
)
def test_production_policy_rejects_lookalikes(prod: CorsPolicy, origin: str) -> None:
    assert not allowed(prod, origin)


def test_regex_does_not_treat_the_dot_in_web_app_as_a_wildcard(
    prod: CorsPolicy,
) -> None:
    assert not allowed(prod, f"https://{SITE}--pr-1-abc123xwebxapp")


def test_regex_is_anchored_to_the_exact_site() -> None:
    policy = cors_policy([], "abcdef")

    assert allowed(policy, "https://abcdef--pr-1-a.web.app")
    assert not allowed(policy, "https://abcdeX--pr-1-a.web.app")
    assert not allowed(policy, "https://abcde--pr-1-a.web.app")


def test_configured_origins_come_first_then_web_app_then_firebaseapp() -> None:
    policy = cors_policy(["http://localhost:5173", "https://a.test"], SITE)

    assert policy.allow_origins == (
        "http://localhost:5173",
        "https://a.test",
        f"https://{SITE}.web.app",
        f"https://{SITE}.firebaseapp.com",
    )


def test_duplicates_are_removed_keeping_the_first_occurrence() -> None:
    policy = cors_policy(
        ["http://a.test", f"https://{SITE}.web.app", "http://b.test", "http://a.test"],
        SITE,
    )

    assert policy.allow_origins == (
        "http://a.test",
        f"https://{SITE}.web.app",
        "http://b.test",
        f"https://{SITE}.firebaseapp.com",
    )


def test_without_a_site_there_are_no_firebase_origins_and_no_regex() -> None:
    policy = cors_policy(["http://localhost:5173"], None)

    assert policy == CorsPolicy(("http://localhost:5173",), None)
    assert not allowed(policy, PREVIEW)


def test_no_origins_and_no_site_allows_nothing() -> None:
    policy = cors_policy([], None)

    assert policy.allow_origins == ()
    assert policy.allow_origin_regex is None


def test_dev_policy_accepts_localhost_and_rejects_others() -> None:
    policy = cors_policy(["http://localhost:5173"], None)

    assert allowed(policy, "http://localhost:5173")
    assert not allowed(policy, "http://localhost:5174")
    assert not allowed(policy, "http://localhost:5173/")


def test_policy_is_deterministic() -> None:
    assert cors_policy(["http://a.test"], SITE) == cors_policy(["http://a.test"], SITE)


def test_accepts_a_tuple_of_origins() -> None:
    assert cors_policy(("http://a.test",), None).allow_origins == ("http://a.test",)


@pytest.mark.parametrize("site", ["abcdef", "a" * 30, "a-b-c-d-e", "a1b2c3"])
def test_valid_site_ids_are_accepted(site: str) -> None:
    assert cors_policy([], site).allow_origins == (
        f"https://{site}.web.app",
        f"https://{site}.firebaseapp.com",
    )


@pytest.mark.parametrize(
    "site",
    [
        "",
        "abcde",  # 5 chars, too short
        "a" * 31,  # too long
        "my--site-x",  # '--' is the channel separator
        "my-site--",
        "--my-site",
        "a--bcdef",
        "Hike-prep",  # uppercase
        "hikePrep1",
        "abcde-",  # trailing hyphen
        "-abcdef",  # leading hyphen
        "1abcdef",  # leading digit
        "abc_def",
        "abc.def",
        "abc def",
        "abcdef\n",  # no trailing-newline acceptance
        "\nabcdef",
        "abcdéf",
        "abc/def",
        "*",
    ],
)
def test_invalid_site_ids_are_rejected(site: str) -> None:
    with pytest.raises(ValueError):
        cors_policy([], site)


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "http://*.test",
        "http://x.test/",
        "http://x.test/path",
        "http://x.test:5173/",
        "http://x.test?a=1",
        "http://x.test#frag",
        "x.test",
        "//x.test",
        "http://",
        "https://",
        "",
        " ",
        "http://x.test ",
        "http://x.test\n",
        "null",
    ],
)
def test_invalid_exact_origins_are_rejected(origin: str) -> None:
    with pytest.raises(ValueError):
        cors_policy([origin], None)


def test_one_bad_origin_among_good_ones_is_rejected() -> None:
    with pytest.raises(ValueError):
        cors_policy(["http://ok.test", "http://bad.test/"], SITE)


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5173", "https://example.com", "https://a.b.example.com:8443"],
)
def test_valid_exact_origins_are_accepted(origin: str) -> None:
    assert cors_policy([origin], None).allow_origins == (origin,)
