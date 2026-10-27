from unittest.mock import MagicMock, patch
import http.cookiejar

from utils.anubis_solver import (
    DEFAULT_USER_AGENT,
    clear_anubis_protected_sites,
    ensure_anubis_session,
    is_anubis_challenge,
    is_site_anubis_protected,
    mark_site_anubis_protected,
    probe_and_solve_anubis,
    solve_anubis_challenge,
    solve_pow,
    solve_sha256_pow,
    validate_anubis_hash,
)


def test_is_anubis_challenge_true_on_challenge_html() -> None:
    html = """
    <html>
      <head><title>Making sure you're not a bot!</title></head>
      <body>
        <script id="anubis_challenge">{"rules": {"algorithm": "argon2id", "difficulty": 4}}</script>
      </body>
    </html>
    """
    assert is_anubis_challenge(html) is True


def test_is_anubis_challenge_false_on_normal_html() -> None:
    html = "<html><head><title>The Bee Dungeon</title></head><body><h1>Chapter 1</h1></body></html>"
    assert is_anubis_challenge(html) is False


def test_is_anubis_challenge_false_on_empty_string() -> None:
    assert is_anubis_challenge("") is False


def test_validate_anubis_hash_bits() -> None:
    # 0x0F -> leading nibble is 0 (first 4 bits: 0000 1111) -> diff 4 matches, diff 5 fails
    h_4bits = bytes([0x0F, 0xFF])
    assert validate_anubis_hash(h_4bits, 4) is True
    assert validate_anubis_hash(h_4bits, 5) is False

    # 0x00 -> leading byte is 0 -> diff 8 matches, diff 9 fails if next byte has leading bit 1
    h_8bits = bytes([0x00, 0x80])
    assert validate_anubis_hash(h_8bits, 8) is True
    assert validate_anubis_hash(h_8bits, 9) is False

    # diff 0 always True
    assert validate_anubis_hash(bytes([0xFF]), 0) is True


def test_solve_pow_finds_matching_hash() -> None:
    test_data = b"test_challenge_data_bytes_123"
    difficulty = 4
    nonce, result_hash = solve_pow(test_data, difficulty, use_le=True)
    assert nonce >= 0
    assert len(result_hash) == 32
    assert validate_anubis_hash(result_hash, difficulty) is True


def test_solve_anubis_challenge_success() -> None:
    challenge_payload = (
        '{"rules": {"algorithm": "argon2id", "difficulty": 2, "extensions": ["css-load"]}, '
        '"challenge": {"id": "test-uuid-1234", "randomData": "deadbeef"}}'
    )
    challenge_html = f"""
    <html>
      <head><title>Making sure you're not a bot!</title></head>
      <body>
        <script id="anubis_challenge">{challenge_payload}</script>
      </body>
    </html>
    """

    mock_session = MagicMock()
    mock_css_resp = MagicMock(status_code=200)
    mock_pass_resp = MagicMock(status_code=200, url="https://royalroad.com/fiction/123")

    mock_session.get.side_effect = [mock_css_resp, mock_pass_resp]
    mock_session.cookies = [
        http.cookiejar.Cookie(
            version=0,
            name="techaro.lol-anubis-auth-test",
            value="token_123",
            port=None,
            port_specified=False,
            domain=".royalroad.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=9999999999,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
    ]

    success = solve_anubis_challenge(
        session=mock_session,
        page_url="https://royalroad.com/fiction/123",
        html=challenge_html,
        user_agent=DEFAULT_USER_AGENT,
    )

    assert success is True
    assert mock_session.get.call_count == 2
    # First call satisfies css-load
    css_call_url = mock_session.get.call_args_list[0][0][0]
    assert "ext/css-load/test-uuid-1234" in css_call_url
    # Second call posts pass-challenge
    pass_call_url = mock_session.get.call_args_list[1][0][0]
    assert "api/pass-challenge" in pass_call_url
    pass_params = mock_session.get.call_args_list[1][1]["params"]
    assert pass_params["id"] == "test-uuid-1234"
    assert "response" in pass_params
    assert "nonce" in pass_params


def test_solve_anubis_challenge_returns_false_on_missing_script() -> None:
    html = "<html><head><title>Making sure you're not a bot!</title></head></html>"
    mock_session = MagicMock()
    success = solve_anubis_challenge(
        session=mock_session,
        page_url="https://royalroad.com/fiction/123",
        html=html,
        user_agent=DEFAULT_USER_AGENT,
    )
    assert success is False


def test_ensure_anubis_session_skips_when_valid_cookie_present() -> None:
    jar = MagicMock()
    mock_cookie = MagicMock()
    mock_cookie.name = "techaro.lol-anubis-auth-xyz"
    mock_cookie.is_expired.return_value = False
    jar.__iter__.return_value = [mock_cookie]

    with patch("requests.Session") as mock_session_cls:
        result_jar = ensure_anubis_session(
            site="royalroad",
            url="https://royalroad.com/fiction/123",
            user_agent=DEFAULT_USER_AGENT,
            cookiejar=jar,
        )
        assert result_jar is jar
        mock_session_cls.assert_not_called()


def test_ensure_anubis_session_solves_and_populates_jar() -> None:
    challenge_payload = (
        '{"rules": {"algorithm": "argon2id", "difficulty": 2}, '
        '"challenge": {"id": "uuid-999", "randomData": "cafe"}}'
    )
    challenge_html = f'<script id="anubis_challenge">{challenge_payload}</script>'

    with patch("requests.Session") as mock_session_cls:
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess

        mock_page_resp = MagicMock(status_code=200, text=challenge_html)
        mock_pass_resp = MagicMock(status_code=200)
        mock_sess.get.side_effect = [mock_page_resp, mock_pass_resp]

        fake_cookie = http.cookiejar.Cookie(
            version=0,
            name="techaro.lol-anubis-auth-999",
            value="token_abc",
            port=None,
            port_specified=False,
            domain=".example.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=9999999999,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
        mock_sess.cookies = [fake_cookie]

        mark_site_anubis_protected("testsite")
        result_jar = ensure_anubis_session(
            site="testsite",
            url="https://example.com/fiction/123",
            user_agent=DEFAULT_USER_AGENT,
            cookiejar=None,
        )

        assert result_jar is not None
        assert getattr(result_jar, "autosave", None) is False
        cookie_names = [c.name for c in result_jar]
        assert "techaro.lol-anubis-auth-999" in cookie_names


def test_solve_anubis_challenge_missing_id_or_random_data() -> None:
    payload = '{"rules": {}, "challenge": {}}'
    html = f'<script id="anubis_challenge">{payload}</script>'
    mock_session = MagicMock()
    success = solve_anubis_challenge(
        session=mock_session,
        page_url="https://royalroad.com/fiction/123",
        html=html,
        user_agent=DEFAULT_USER_AGENT,
    )
    assert success is False


def test_solve_anubis_challenge_pass_failure_status_code() -> None:
    payload = (
        '{"rules": {"difficulty": 1}, "challenge": {"id": "cid", "randomData": "ab"}}'
    )
    html = f'<script id="anubis_challenge">{payload}</script>'
    mock_session = MagicMock()
    mock_resp = MagicMock(status_code=403)
    mock_session.get.return_value = mock_resp
    success = solve_anubis_challenge(
        session=mock_session,
        page_url="https://royalroad.com/fiction/123",
        html=html,
        user_agent=DEFAULT_USER_AGENT,
    )
    assert success is False


def test_solve_anubis_challenge_css_load_exception_continues() -> None:
    payload = '{"rules": {"difficulty": 1, "extensions": ["css-load"]}, "challenge": {"id": "cid", "randomData": "ab"}}'
    html = f'<script id="anubis_challenge">{payload}</script>'
    mock_session = MagicMock()
    mock_session.get.side_effect = [
        RuntimeError("css load failed"),
        MagicMock(status_code=200),
    ]
    success = solve_anubis_challenge(
        session=mock_session,
        page_url="https://royalroad.com/fiction/123",
        html=html,
        user_agent=DEFAULT_USER_AGENT,
    )
    assert success is True


def test_ensure_anubis_session_unprotected_site_returns_immediately() -> None:
    jar = MagicMock()
    with patch("requests.Session") as mock_sess:
        res = ensure_anubis_session(
            site="archiveofourown",
            url="https://archiveofourown.org/works/1",
            user_agent=DEFAULT_USER_AGENT,
            cookiejar=jar,
        )
        assert res is jar
        mock_sess.assert_not_called()


def test_ensure_anubis_session_probe_not_challenged_syncs_cookies() -> None:
    with patch("requests.Session") as mock_session_cls:
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.return_value = MagicMock(
            status_code=200, text="<html>Normal Story</html>"
        )
        cookie = MagicMock()
        mock_sess.cookies = [cookie]

        mark_site_anubis_protected("testsite")
        res = ensure_anubis_session(
            site="testsite",
            url="https://example.com/fiction/123",
            user_agent=DEFAULT_USER_AGENT,
            cookiejar=None,
        )
        assert res is not None


def test_ensure_anubis_session_probe_exception_handled() -> None:
    with patch("requests.Session") as mock_session_cls:
        mock_sess = MagicMock()
        mock_session_cls.return_value = mock_sess
        mock_sess.get.side_effect = RuntimeError("probe error")

        mark_site_anubis_protected("testsite")
        res = ensure_anubis_session(
            site="testsite",
            url="https://example.com/fiction/123",
            user_agent=DEFAULT_USER_AGENT,
            cookiejar=None,
        )
        assert res is not None


def test_site_anubis_protection_registration() -> None:
    clear_anubis_protected_sites()
    assert is_site_anubis_protected("some_site") is False
    assert is_site_anubis_protected("scribblehub") is False
    assert is_site_anubis_protected("") is False

    mark_site_anubis_protected("scribblehub")
    assert is_site_anubis_protected("scribblehub") is True
    assert is_site_anubis_protected("SCRIBBLEHUB") is True

    clear_anubis_protected_sites()
    assert is_site_anubis_protected("scribblehub") is False


def test_probe_and_solve_anubis_detects_and_solves() -> None:
    challenge_payload = (
        '{"rules": {"algorithm": "argon2id", "difficulty": 2}, '
        '"challenge": {"id": "cid-abc", "randomData": "1234"}}'
    )
    challenge_html = f'<script id="anubis_challenge">{challenge_payload}</script>'

    with patch("requests.Session") as mock_sess_cls:
        mock_sess = MagicMock()
        mock_sess_cls.return_value = mock_sess
        mock_page_resp = MagicMock(status_code=200, text=challenge_html)
        mock_pass_resp = MagicMock(status_code=200)
        mock_sess.get.side_effect = [mock_page_resp, mock_pass_resp]

        fake_cookie = http.cookiejar.Cookie(
            version=0,
            name="techaro.lol-anubis-auth-xyz",
            value="token",
            port=None,
            port_specified=False,
            domain=".example.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=9999999999,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
        mock_sess.cookies = [fake_cookie]

        solved, jar = probe_and_solve_anubis(
            url="https://example.com/fiction/1",
            user_agent=DEFAULT_USER_AGENT,
            cookiejar=None,
        )

        assert solved is True
        assert "techaro.lol-anubis-auth-xyz" in [c.name for c in jar]


def test_probe_and_solve_anubis_returns_false_when_not_challenged() -> None:
    with patch("requests.Session") as mock_sess_cls:
        mock_sess = MagicMock()
        mock_sess_cls.return_value = mock_sess
        mock_page_resp = MagicMock(status_code=404, text="<html>Story not found</html>")
        mock_sess.get.return_value = mock_page_resp

        solved, jar = probe_and_solve_anubis(
            url="https://example.com/fiction/1",
            user_agent=DEFAULT_USER_AGENT,
            cookiejar=None,
        )

        assert solved is False


def test_probe_and_solve_anubis_normalizes_schemeless_url() -> None:
    with patch("requests.Session") as mock_sess_cls:
        mock_sess = MagicMock()
        mock_sess_cls.return_value = mock_sess
        mock_sess.get.return_value = MagicMock(
            status_code=200, text="<html>Normal</html>"
        )

        solved, _ = probe_and_solve_anubis(
            url="royalroad.com/fiction/129182",
            user_agent=DEFAULT_USER_AGENT,
            cookiejar=None,
        )

        assert solved is False
        mock_sess.get.assert_called_once_with(
            "https://royalroad.com/fiction/129182", timeout=15
        )


def test_probe_and_solve_anubis_empty_or_epub_url_returns_false() -> None:
    solved, _ = probe_and_solve_anubis(
        url="",
        user_agent=DEFAULT_USER_AGENT,
        cookiejar=None,
    )
    assert solved is False


def test_solve_sha256_pow_finds_hash_with_leading_zeroes() -> None:
    random_data = "6aecd0a2d854c6a1e27afa4dc07968c0"
    difficulty = 3
    nonce, result_hash = solve_sha256_pow(random_data, difficulty)
    assert nonce >= 0
    assert result_hash.startswith("000")


def test_solve_anubis_challenge_fast_algorithm_sha256() -> None:
    challenge_payload = (
        '{"rules": {"algorithm": "fast", "difficulty": 2}, '
        '"challenge": {"id": "fast-uuid-1", "randomData": "deadbeef123"}}'
    )
    challenge_html = f'<script id="anubis_challenge">{challenge_payload}</script>'

    mock_session = MagicMock()
    mock_pass_resp = MagicMock(status_code=200, history=[])
    mock_session.get.return_value = mock_pass_resp
    mock_session.cookies = [
        http.cookiejar.Cookie(
            version=0,
            name="techaro.lol-anubis-auth-xyz",
            value="token",
            port=None,
            port_specified=False,
            domain=".royalroad.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=9999999999,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
    ]

    success = solve_anubis_challenge(
        session=mock_session,
        page_url="https://www.royalroad.com/fiction/127120",
        html=challenge_html,
        user_agent=DEFAULT_USER_AGENT,
    )
    assert success is True
    # Verify that SHA-256 solution was submitted
    assert mock_session.get.call_count == 1
    call_args = mock_session.get.call_args
    params = call_args[1]["params"]
    assert params["id"] == "fast-uuid-1"
    assert params["response"].startswith("00")


def test_solve_anubis_challenge_accepts_302_redirect_status() -> None:
    challenge_payload = (
        '{"rules": {"algorithm": "fast", "difficulty": 2}, '
        '"challenge": {"id": "uuid-302", "randomData": "feedface"}}'
    )
    challenge_html = f'<script id="anubis_challenge">{challenge_payload}</script>'

    mock_session = MagicMock()
    mock_pass_resp = MagicMock(status_code=302, history=[])
    mock_session.get.return_value = mock_pass_resp
    mock_session.cookies = [
        http.cookiejar.Cookie(
            version=0,
            name="techaro.lol-anubis-auth-302",
            value="token_jwt",
            port=None,
            port_specified=False,
            domain=".royalroad.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=9999999999,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
        )
    ]

    success = solve_anubis_challenge(
        session=mock_session,
        page_url="https://www.royalroad.com/fiction/127120",
        html=challenge_html,
        user_agent=DEFAULT_USER_AGENT,
    )
    assert success is True
