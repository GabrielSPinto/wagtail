# test_mcdc_middleware.py
import urllib.parse

from django.test import TestCase, override_settings
from wagtail.contrib.redirects.models import Redirect
from wagtail.models import Site
from wagtail.test.utils import WagtailTestUtils


@override_settings(
    ALLOWED_HOSTS=["testserver", "sitea.test", "siteb.test", "localhost"],
    WAGTAIL_REDIRECTS_ENABLED=True,
    # toggles de normalização (pode variar por versão; se não existir, é ignorado)
    WAGTAIL_REDIRECTS_APPEND_SLASH=True,
    APPEND_SLASH=True,
)
class TestRedirectMiddlewareMCDC(WagtailTestUtils, TestCase):
    """
    CT1..CT9 para RedirectMiddleware.__call__ (MC/DC simplificado):
      - site match vs fallback global
      - permanent (301) vs temporary (302)
      - preserve querystring on/off
      - normalização de barra final on/off
      - ausência de regra / regra em outro site / precedência site>global
    """

    def setUp(self):
        self.login()

        # Site A (default) e Site B
        self.site_a = Site.objects.get(is_default_site=True)
        self.site_a.hostname = "sitea.test"
        self.site_a.save()

        self.site_b = Site.objects.create(
            hostname="siteb.test", root_page=self.site_a.root_page
        )

    # ---------- utils ----------
    def _request(self, path, host="sitea.test"):
        return self.client.get(path, HTTP_HOST=host, follow=False)

    def _mk_redirect(
        self,
        old_path,
        to,
        *,
        site=None,
        permanent=True,
        preserve_query=True,
    ):
        """
        Cria regra no modelo Redirect (ajuste nomes se sua versão divergir).
        """
        kwargs = {
            "old_path": old_path,
            "redirect_link": to,
            "is_permanent": permanent,
            "automatically_append_querystring": preserve_query,
        }
        if site is not None:
            kwargs["site"] = site
        return Redirect.objects.create(**kwargs)

    # ---------- CTs ----------

    def test_CT1_permanent_with_query_preserved(self):
        """CT1: site=A, regra local, 301 + preserva query."""
        self._mk_redirect("/old/", "/new/", site=self.site_a, permanent=True, preserve_query=True)
        resp = self._request("/old/?q=1")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/new/?q=1")

    def test_CT2_no_rule_returns_404(self):
        """CT2: site=A sem regra para o path -> 404 (nenhum redirect)."""
        resp = self._request("/no-rule-here/")
        self.assertEqual(resp.status_code, 404)

    def test_CT3_rule_exists_only_for_other_site(self):
        """CT3: regra só no site=B; requisição em site=A não deve redirecionar."""
        self._mk_redirect("/only-b/", "/dest-b/", site=self.site_b, permanent=True)
        resp = self._request("/only-b/", host="sitea.test")
        self.assertEqual(resp.status_code, 404)

    def test_CT4_site_rule_precedes_global(self):
        """CT4: existem regra global e regra do site; prevalece a do site."""
        self._mk_redirect("/conflict/", "/global-dest/", site=None, permanent=False)
        self._mk_redirect("/conflict/", "/site-dest/", site=self.site_a, permanent=True)
        resp = self._request("/conflict/")
        # Deve aplicar a regra do site (301 para /site-dest/)
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/site-dest/")

    def test_CT5_fallback_global_temporary_no_query(self):
        """CT5: sem regra do site; regra global temporária, descarta query."""
        self._mk_redirect("/legacy", "/novo", site=None, permanent=False, preserve_query=False)
        resp = self._request("/legacy?q=1")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/novo")

    @override_settings(WAGTAIL_REDIRECTS_APPEND_SLASH=True, APPEND_SLASH=True)
    def test_CT6_normalization_on_finds_rule(self):
        """CT6: regra cadastrada com '/old/'; acesso '/old' com normalização ON."""
        self._mk_redirect("/old/", "/new/", site=self.site_a, permanent=True, preserve_query=False)
        resp = self._request("/old")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/new/")

    @override_settings(WAGTAIL_REDIRECTS_APPEND_SLASH=False, APPEND_SLASH=False)
    def test_CT7_normalization_off_does_not_find(self):
        """CT7: mesmo path do CT6, mas normalização OFF -> não encontra, 404."""
        self._mk_redirect("/old/", "/new/", site=self.site_a, permanent=True, preserve_query=False)
        resp = self._request("/old")
        self.assertEqual(resp.status_code, 404)

    def test_CT8_temporary_with_query_preserved(self):
        """CT8: regra do site temporária (302) preservando query."""
        self._mk_redirect("/old-tmp/", "/new-tmp/", site=self.site_a, permanent=False, preserve_query=True)
        resp = self._request("/old-tmp/?search=abc")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/new-tmp/?search=abc")

    def test_CT9_permanent_drop_query(self):
        """CT9: regra do site permanente (301) descartando query."""
        self._mk_redirect("/old-drop/", "/new-drop/", site=self.site_a, permanent=True, preserve_query=False)
        resp = self._request("/old-drop/?x=1&y=2")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/new-drop/")
