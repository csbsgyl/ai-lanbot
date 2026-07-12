import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  RotateCcw,
  Save,
  Trash2,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { backendClient } from '@/app/infra/http';
import type { ApiRespIDCQueryConfig } from '@/app/infra/entities/api';
import {
  PanelBody,
  PanelToolbar,
} from '@/app/home/components/settings-dialog/panel-layout';

interface IDCQuerySettingsPanelProps {
  active: boolean;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'object' && error && 'msg' in error) {
    return String((error as { msg?: unknown }).msg || '');
  }
  return String(error);
}

export default function IDCQuerySettingsPanel({
  active,
}: IDCQuerySettingsPanelProps) {
  const { t } = useTranslation();
  const [baseUrl, setBaseUrl] = useState('');
  const [token, setToken] = useState('');
  const [timeoutSeconds, setTimeoutSeconds] = useState('8');
  const [verifyTls, setVerifyTls] = useState(true);
  const [configured, setConfigured] = useState(false);
  const [tokenConfigured, setTokenConfigured] = useState(false);
  const [clearToken, setClearToken] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const applyConfig = useCallback((config: ApiRespIDCQueryConfig) => {
    setBaseUrl(config.base_url);
    setTimeoutSeconds(String(config.timeout_seconds));
    setVerifyTls(config.verify_tls);
    setConfigured(config.configured);
    setTokenConfigured(config.token_configured);
    setToken('');
    setClearToken(false);
    setLoaded(true);
  }, []);

  const loadConfig = useCallback(async () => {
    setLoaded(false);
    setLoading(true);
    setError('');
    try {
      applyConfig(await backendClient.getIDCQueryConfig());
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [applyConfig]);

  useEffect(() => {
    if (active) loadConfig();
  }, [active, loadConfig]);

  const saveConfig = async () => {
    const parsedTimeout = Number(timeoutSeconds);
    if (
      !Number.isFinite(parsedTimeout) ||
      parsedTimeout < 1 ||
      parsedTimeout > 120
    ) {
      toast.error(t('idcQuery.invalidTimeout'));
      return;
    }

    setSaving(true);
    try {
      const nextConfig = await backendClient.updateIDCQueryConfig({
        base_url: baseUrl.trim(),
        timeout_seconds: parsedTimeout,
        verify_tls: verifyTls,
        clear_token: clearToken,
        ...(token.trim() ? { token: token.trim() } : {}),
      });
      applyConfig(nextConfig);
      toast.success(t('idcQuery.saveSuccess'));
    } catch (saveError) {
      toast.error(`${t('idcQuery.saveError')}: ${getErrorMessage(saveError)}`);
    } finally {
      setSaving(false);
    }
  };

  const handleTokenAction = () => {
    if (clearToken) {
      setClearToken(false);
      return;
    }
    if (token) {
      setToken('');
      setClearToken(tokenConfigured);
      return;
    }
    if (tokenConfigured) setClearToken(true);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PanelToolbar>
        <Badge variant={configured ? 'secondary' : 'outline'}>
          {configured && <CheckCircle2 className="size-3" />}
          {t(configured ? 'idcQuery.configured' : 'idcQuery.notConfigured')}
        </Badge>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={loadConfig}
            disabled={loading || saving}
            aria-label={t('idcQuery.refresh')}
            title={t('idcQuery.refresh')}
          >
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
          <Button
            type="submit"
            form="idc-query-settings-form"
            size="sm"
            disabled={!loaded || loading || saving}
          >
            {saving ? <Loader2 className="animate-spin" /> : <Save />}
            {saving ? t('idcQuery.saving') : t('idcQuery.save')}
          </Button>
        </div>
      </PanelToolbar>

      <PanelBody>
        {loading ? (
          <div className="flex min-h-48 items-center justify-center text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            {t('idcQuery.loading')}
          </div>
        ) : error ? (
          <div className="flex min-h-48 flex-col items-center justify-center gap-3 text-center">
            <AlertTriangle className="size-5 text-destructive" />
            <p className="max-w-md break-words text-sm text-muted-foreground">
              {t('idcQuery.loadError')}: {error}
            </p>
            <Button type="button" variant="outline" onClick={loadConfig}>
              <RefreshCw />
              {t('idcQuery.retry')}
            </Button>
          </div>
        ) : (
          <form
            id="idc-query-settings-form"
            className="mx-auto w-full max-w-2xl space-y-7"
            onSubmit={(event) => {
              event.preventDefault();
              saveConfig();
            }}
          >
            <section className="space-y-4 border-b pb-7">
              <h3 className="text-sm font-semibold">{t('idcQuery.gateway')}</h3>
              <div className="space-y-2">
                <Label htmlFor="idc-query-base-url">
                  {t('idcQuery.gatewayUrl')}
                </Label>
                <Input
                  id="idc-query-base-url"
                  type="url"
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                  placeholder={t('idcQuery.gatewayUrlPlaceholder')}
                  maxLength={2048}
                  autoComplete="url"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="idc-query-timeout">
                  {t('idcQuery.timeout')}
                </Label>
                <div className="flex max-w-48 items-center gap-2">
                  <Input
                    id="idc-query-timeout"
                    type="number"
                    min={1}
                    max={120}
                    step="0.5"
                    value={timeoutSeconds}
                    onChange={(event) => setTimeoutSeconds(event.target.value)}
                    className="tabular-nums"
                  />
                  <span className="shrink-0 text-sm text-muted-foreground">
                    {t('idcQuery.seconds')}
                  </span>
                </div>
              </div>
            </section>

            <section className="space-y-4">
              <h3 className="text-sm font-semibold">
                {t('idcQuery.security')}
              </h3>
              <div className="space-y-2">
                <div className="flex min-h-6 items-center justify-between gap-3">
                  <Label htmlFor="idc-query-token">
                    {t('idcQuery.serviceToken')}
                  </Label>
                  <Badge variant="outline">
                    {t(
                      tokenConfigured
                        ? 'idcQuery.tokenConfigured'
                        : 'idcQuery.tokenNotConfigured',
                    )}
                  </Badge>
                </div>
                <div className="flex items-center gap-2">
                  <Input
                    id="idc-query-token"
                    type="password"
                    value={token}
                    disabled={clearToken}
                    onChange={(event) => {
                      setToken(event.target.value);
                      setClearToken(false);
                    }}
                    placeholder={t(
                      tokenConfigured
                        ? 'idcQuery.tokenConfiguredPlaceholder'
                        : 'idcQuery.tokenPlaceholder',
                    )}
                    maxLength={8192}
                    autoComplete="new-password"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    onClick={handleTokenAction}
                    disabled={!clearToken && !token && !tokenConfigured}
                  >
                    {clearToken ? <RotateCcw /> : <Trash2 />}
                    {t(
                      clearToken ? 'idcQuery.keepToken' : 'idcQuery.clearToken',
                    )}
                  </Button>
                </div>
                {clearToken && (
                  <p className="text-sm text-destructive">
                    {t('idcQuery.tokenPendingClear')}
                  </p>
                )}
              </div>

              <div className="flex items-center justify-between gap-4 border-t pt-5">
                <Label htmlFor="idc-query-verify-tls">
                  {t('idcQuery.verifyTls')}
                </Label>
                <Switch
                  id="idc-query-verify-tls"
                  checked={verifyTls}
                  onCheckedChange={setVerifyTls}
                />
              </div>
              {!verifyTls && (
                <div className="flex items-center gap-2 text-sm text-destructive">
                  <AlertTriangle className="size-4" />
                  {t('idcQuery.tlsDisabled')}
                </div>
              )}
            </section>
          </form>
        )}
      </PanelBody>
    </div>
  );
}
