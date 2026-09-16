def test_i18n_languages_and_bundle(client):
    langs = client.get("/api/v1/i18n/languages")
    assert langs.status_code == 200
    codes = {x["code"] for x in langs.json()}
    assert "en" in codes and "zh-CN" in codes

    en = client.get("/api/v1/i18n/bundle?locale=en")
    assert en.status_code == 200
    assert en.json()["messages"]["nav.home"]
    assert en.json()["terms"]["term.tce"]["label"]

    zh = client.get("/api/v1/i18n/bundle?locale=zh-CN")
    assert zh.status_code == 200
    assert zh.json()["messages"]["nav.home"] == "工作台"
    assert "TCE" in zh.json()["terms"]["term.tce"]["label"] or "期租" in zh.json()["terms"]["term.tce"]["label"]


def test_platform_and_tenant_i18n_admin(client, auth_headers):
    # platform
    ops = client.post(
        "/api/v1/auth/login",
        json={"email": "ops@marios.platform", "password": "Ops1234!", "tenant_code": "sys"},
    )
    ph = {"Authorization": f"Bearer {ops.json()['access_token']}"}
    ov = client.get("/api/v1/platform/i18n/overview", headers=ph)
    assert ov.status_code == 200
    assert ov.json()["terminology_terms"] >= 100
    assert ov.json()["ui_message_keys"] >= 20

    put_msg = client.put(
        "/api/v1/platform/i18n/messages",
        headers=ph,
        json={"msg_key": "nav.home", "locale": "zh-CN", "text": "工作台", "namespace": "nav"},
    )
    assert put_msg.status_code == 200

    # tenant
    h = auth_headers
    settings = client.put(
        "/api/v1/admin/i18n/settings",
        headers=h,
        json={"default_locale": "zh-CN", "allow_user_override": True},
    )
    assert settings.status_code == 200
    assert settings.json()["default_locale"] == "zh-CN"

    ovrd = client.put(
        "/api/v1/admin/i18n/terminology/overrides",
        headers=h,
        json={"term_key": "term.tce", "locale": "zh-CN", "label": "公司定制TCE"},
    )
    assert ovrd.status_code == 200

    bundle = client.get("/api/v1/i18n/bundle?locale=zh-CN", headers=h)
    assert bundle.status_code == 200
    assert bundle.json()["terms"]["term.tce"]["label"] == "公司定制TCE"


def test_user_locale_switch(client, auth_headers):
    h = auth_headers
    r = client.put("/api/v1/me/locale", headers=h, json={"locale": "zh-CN"})
    assert r.status_code == 200
    assert r.json()["locale"] == "zh-CN"
    me = client.get("/api/v1/me", headers=h)
    assert me.status_code == 200
    assert (me.json()["user"]["locale"] or "").startswith("zh-CN")
