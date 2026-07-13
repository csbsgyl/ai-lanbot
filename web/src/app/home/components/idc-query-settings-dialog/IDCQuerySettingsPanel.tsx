import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Activity,
  AlertTriangle,
  Cable,
  CheckCircle2,
  Link2,
  Loader2,
  RefreshCw,
  RotateCcw,
  Save,
  Settings2,
  Trash2,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { backendClient } from '@/app/infra/http';
import type {
  ApiRespIDCQueryConfig,
  ApiRespIDCQueryConnectionTest,
  IDCQueryAuditEvent,
  IDCQueryBinding,
} from '@/app/infra/entities/api';
import {
  PanelBody,
  PanelToolbar,
} from '@/app/home/components/settings-dialog/panel-layout';
import IDCQueryAuditTable from './IDCQueryAuditTable';
import IDCQueryBindingTable from './IDCQueryBindingTable';

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
  const [activeTab, setActiveTab] = useState('configuration');
  const [baseUrl, setBaseUrl] = useState('');
  const [token, setToken] = useState('');
  const [timeoutSeconds, setTimeoutSeconds] = useState('8');
  const [requestsPerMinute, setRequestsPerMinute] = useState('20');
  const [bindAttemptsPer10Minutes, setBindAttemptsPer10Minutes] = useState('5');
  const [verifyTls, setVerifyTls] = useState(true);
  const [configured, setConfigured] = useState(false);
  const [tokenConfigured, setTokenConfigured] = useState(false);
  const [clearToken, setClearToken] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testingConnection, setTestingConnection] = useState(false);
  const [connectionResult, setConnectionResult] =
    useState<ApiRespIDCQueryConnectionTest | null>(null);
  const connectionTestSequence = useRef(0);
  const [error, setError] = useState('');
  const [auditEvents, setAuditEvents] = useState<IDCQueryAuditEvent[]>([]);
  const [auditGeneratedAt, setAuditGeneratedAt] = useState('');
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState('');
  const [bindings, setBindings] = useState<IDCQueryBinding[]>([]);
  const [bindingsTotal, setBindingsTotal] = useState(0);
  const [bindingsGeneratedAt, setBindingsGeneratedAt] = useState('');
  const [bindingsLoading, setBindingsLoading] = useState(false);
  const [bindingsError, setBindingsError] = useState('');

  const invalidateConnectionResult = useCallback(() => {
    connectionTestSequence.current += 1;
    setConnectionResult(null);
  }, []);

  const applyConfig = useCallback(
    (config: ApiRespIDCQueryConfig) => {
      setBaseUrl(config.base_url);
      setTimeoutSeconds(String(config.timeout_seconds));
      setRequestsPerMinute(String(config.requests_per_minute));
      setBindAttemptsPer10Minutes(String(config.bind_attempts_per_10_minutes));
      setVerifyTls(config.verify_tls);
      setConfigured(config.configured);
      setTokenConfigured(config.token_configured);
      setToken('');
      setClearToken(false);
      invalidateConnectionResult();
      setLoaded(true);
    },
    [invalidateConnectionResult],
  );

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

  const loadAudit = useCallback(async () => {
    setAuditLoading(true);
    setAuditError('');
    try {
      const result = await backendClient.getIDCQueryAudit(100);
      setAuditEvents(result.events);
      setAuditGeneratedAt(result.generated_at);
    } catch (loadError) {
      setAuditError(getErrorMessage(loadError));
    } finally {
      setAuditLoading(false);
    }
  }, []);

  const loadBindings = useCallback(async () => {
    setBindingsLoading(true);
    setBindingsError('');
    try {
      const result = await backendClient.getIDCQueryBindings(200);
      setBindings(result.bindings);
      setBindingsTotal(result.total);
      setBindingsGeneratedAt(result.generated_at);
    } catch (loadError) {
      setBindingsError(getErrorMessage(loadError));
    } finally {
      setBindingsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (active) loadConfig();
  }, [active, loadConfig]);

  useEffect(() => {
    if (active && activeTab === 'audit') loadAudit();
  }, [active, activeTab, loadAudit]);

  useEffect(() => {
    if (active && activeTab === 'bindings') loadBindings();
  }, [active, activeTab, loadBindings]);

  const saveConfig = async () => {
    const parsedTimeout = Number(timeoutSeconds);
    const parsedRequestsPerMinute = Number(requestsPerMinute);
    const parsedBindAttempts = Number(bindAttemptsPer10Minutes);
    if (
      !Number.isFinite(parsedTimeout) ||
      parsedTimeout < 1 ||
      parsedTimeout > 120
    ) {
      toast.error(t('idcQuery.invalidTimeout'));
      return;
    }
    if (
      !Number.isInteger(parsedRequestsPerMinute) ||
      parsedRequestsPerMinute < 1 ||
      parsedRequestsPerMinute > 1000 ||
      !Number.isInteger(parsedBindAttempts) ||
      parsedBindAttempts < 1 ||
      parsedBindAttempts > 1000
    ) {
      toast.error(t('idcQuery.invalidRateLimit'));
      return;
    }

    setSaving(true);
    try {
      const nextConfig = await backendClient.updateIDCQueryConfig({
        base_url: baseUrl.trim(),
        timeout_seconds: parsedTimeout,
        verify_tls: verifyTls,
        requests_per_minute: parsedRequestsPerMinute,
        bind_attempts_per_10_minutes: parsedBindAttempts,
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

  const testConnection = async () => {
    const parsedTimeout = Number(timeoutSeconds);
    if (!baseUrl.trim()) {
      toast.error(t('idcQuery.connection.urlRequired'));
      return;
    }
    if (
      !Number.isFinite(parsedTimeout) ||
      parsedTimeout < 1 ||
      parsedTimeout > 120
    ) {
      toast.error(t('idcQuery.invalidTimeout'));
      return;
    }

    setTestingConnection(true);
    setConnectionResult(null);
    const testSequence = ++connectionTestSequence.current;
    try {
      const result = await backendClient.testIDCQueryConnection({
        base_url: baseUrl.trim(),
        timeout_seconds: parsedTimeout,
        verify_tls: verifyTls,
        clear_token: clearToken,
        ...(token.trim() ? { token: token.trim() } : {}),
      });
      if (connectionTestSequence.current === testSequence) {
        setConnectionResult(result);
      }
    } catch (testError) {
      toast.error(
        `${t('idcQuery.connection.testError')}: ${getErrorMessage(testError)}`,
      );
    } finally {
      setTestingConnection(false);
    }
  };

  const handleTokenAction = () => {
    invalidateConnectionResult();
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
    <Tabs
      value={activeTab}
      onValueChange={setActiveTab}
      className="flex h-full min-h-0 flex-col overflow-hidden"
    >
      <PanelToolbar>
        <TabsList>
          <TabsTrigger
            value="configuration"
            aria-label={t('idcQuery.tabs.configuration')}
            title={t('idcQuery.tabs.configuration')}
          >
            <Settings2 />
            <span className="hidden sm:inline">
              {t('idcQuery.tabs.configuration')}
            </span>
          </TabsTrigger>
          <TabsTrigger
            value="bindings"
            aria-label={t('idcQuery.tabs.bindings')}
            title={t('idcQuery.tabs.bindings')}
          >
            <Link2 />
            <span className="hidden sm:inline">
              {t('idcQuery.tabs.bindings')}
            </span>
          </TabsTrigger>
          <TabsTrigger
            value="audit"
            aria-label={t('idcQuery.tabs.audit')}
            title={t('idcQuery.tabs.audit')}
          >
            <Activity />
            <span className="hidden sm:inline">{t('idcQuery.tabs.audit')}</span>
          </TabsTrigger>
        </TabsList>

        {activeTab === 'configuration' ? (
          <div className="flex items-center gap-2">
            <Badge variant={configured ? 'secondary' : 'outline'}>
              {configured && <CheckCircle2 className="size-3" />}
              {t(configured ? 'idcQuery.configured' : 'idcQuery.notConfigured')}
            </Badge>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={testConnection}
              disabled={!loaded || loading || saving || testingConnection}
              aria-label={t('idcQuery.connection.test')}
              title={t('idcQuery.connection.test')}
            >
              {testingConnection ? (
                <Loader2 className="animate-spin" />
              ) : (
                <Cable />
              )}
              <span className="hidden lg:inline">
                {t(
                  testingConnection
                    ? 'idcQuery.connection.testing'
                    : 'idcQuery.connection.test',
                )}
              </span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={loadConfig}
              disabled={loading || saving || testingConnection}
              aria-label={t('idcQuery.refresh')}
              title={t('idcQuery.refresh')}
            >
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
            <Button
              type="submit"
              form="idc-query-settings-form"
              size="sm"
              disabled={!loaded || loading || saving || testingConnection}
            >
              {saving ? <Loader2 className="animate-spin" /> : <Save />}
              {saving ? t('idcQuery.saving') : t('idcQuery.save')}
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={activeTab === 'bindings' ? loadBindings : loadAudit}
            disabled={activeTab === 'bindings' ? bindingsLoading : auditLoading}
            aria-label={t(
              activeTab === 'bindings'
                ? 'idcQuery.bindings.refresh'
                : 'idcQuery.audit.refresh',
            )}
            title={t(
              activeTab === 'bindings'
                ? 'idcQuery.bindings.refresh'
                : 'idcQuery.audit.refresh',
            )}
          >
            <RefreshCw
              className={
                (activeTab === 'bindings' ? bindingsLoading : auditLoading)
                  ? 'animate-spin'
                  : ''
              }
            />
          </Button>
        )}
      </PanelToolbar>

      <TabsContent
        value="configuration"
        className="mt-0 min-h-0 flex-1 data-[state=active]:flex data-[state=active]:flex-col"
      >
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
                <h3 className="text-sm font-semibold">
                  {t('idcQuery.gateway')}
                </h3>
                <div className="space-y-2">
                  <Label htmlFor="idc-query-base-url">
                    {t('idcQuery.gatewayUrl')}
                  </Label>
                  <Input
                    id="idc-query-base-url"
                    type="url"
                    value={baseUrl}
                    onChange={(event) => {
                      setBaseUrl(event.target.value);
                      invalidateConnectionResult();
                    }}
                    placeholder={t('idcQuery.gatewayUrlPlaceholder')}
                    maxLength={2048}
                    autoComplete="url"
                  />
                </div>

                {connectionResult && (
                  <div
                    className={`flex items-start gap-3 border-l-2 px-3 py-2 ${
                      connectionResult.status === 'reachable'
                        ? 'border-green-600 bg-green-500/5'
                        : 'border-destructive bg-destructive/5'
                    }`}
                  >
                    {connectionResult.status === 'reachable' ? (
                      <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-green-600" />
                    ) : (
                      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
                    )}
                    <div className="min-w-0 space-y-1">
                      <p className="text-sm font-medium">
                        {t(
                          `idcQuery.connection.status.${connectionResult.status}`,
                        )}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {t('idcQuery.connection.details', {
                          httpStatus:
                            connectionResult.http_status ??
                            t('idcQuery.connection.notAvailable'),
                          latency: connectionResult.latency_ms,
                          tls: t(
                            `idcQuery.connection.tls.${connectionResult.tls_status}`,
                          ),
                        })}
                      </p>
                      {connectionResult.token_configured && (
                        <p className="text-xs text-muted-foreground">
                          {t(
                            connectionResult.auth_status === 'rejected'
                              ? 'idcQuery.connection.authRejected'
                              : 'idcQuery.connection.authNotVerified',
                          )}
                        </p>
                      )}
                    </div>
                  </div>
                )}

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
                      onChange={(event) => {
                        setTimeoutSeconds(event.target.value);
                        invalidateConnectionResult();
                      }}
                      className="tabular-nums"
                    />
                    <span className="shrink-0 text-sm text-muted-foreground">
                      {t('idcQuery.seconds')}
                    </span>
                  </div>
                </div>
              </section>

              <section className="space-y-4 border-b pb-7">
                <h3 className="text-sm font-semibold">
                  {t('idcQuery.protection')}
                </h3>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="idc-query-requests-per-minute">
                      {t('idcQuery.requestsPerMinute')}
                    </Label>
                    <Input
                      id="idc-query-requests-per-minute"
                      type="number"
                      min={1}
                      max={1000}
                      step={1}
                      value={requestsPerMinute}
                      onChange={(event) =>
                        setRequestsPerMinute(event.target.value)
                      }
                      className="tabular-nums"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="idc-query-bind-attempts">
                      {t('idcQuery.bindAttemptsPer10Minutes')}
                    </Label>
                    <Input
                      id="idc-query-bind-attempts"
                      type="number"
                      min={1}
                      max={1000}
                      step={1}
                      value={bindAttemptsPer10Minutes}
                      onChange={(event) =>
                        setBindAttemptsPer10Minutes(event.target.value)
                      }
                      className="tabular-nums"
                    />
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
                        invalidateConnectionResult();
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
                        clearToken
                          ? 'idcQuery.keepToken'
                          : 'idcQuery.clearToken',
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
                    onCheckedChange={(checked) => {
                      setVerifyTls(checked);
                      invalidateConnectionResult();
                    }}
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
      </TabsContent>

      <TabsContent
        value="bindings"
        className="mt-0 min-h-0 flex-1 data-[state=active]:flex data-[state=active]:flex-col"
      >
        <IDCQueryBindingTable
          bindings={bindings}
          generatedAt={bindingsGeneratedAt}
          total={bindingsTotal}
          loading={bindingsLoading}
          error={bindingsError}
          onRetry={loadBindings}
        />
      </TabsContent>

      <TabsContent
        value="audit"
        className="mt-0 min-h-0 flex-1 data-[state=active]:flex data-[state=active]:flex-col"
      >
        <IDCQueryAuditTable
          events={auditEvents}
          generatedAt={auditGeneratedAt}
          loading={auditLoading}
          error={auditError}
          onRetry={loadAudit}
        />
      </TabsContent>
    </Tabs>
  );
}
