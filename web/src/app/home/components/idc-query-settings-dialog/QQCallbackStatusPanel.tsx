import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Loader2,
  RadioTower,
  RefreshCw,
} from 'lucide-react';
import type {
  ApiRespQQOfficialStatus,
  QQOfficialCallbackStatus,
} from '@/app/infra/entities/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PanelBody } from '@/app/home/components/settings-dialog/panel-layout';
import { formatTimestamp } from './display';

interface QQCallbackStatusPanelProps {
  status: ApiRespQQOfficialStatus | null;
  loading: boolean;
  error: string;
  onRetry: () => void;
}

function statusVariant(
  status: QQOfficialCallbackStatus,
): 'secondary' | 'outline' | 'destructive' {
  if (status === 'ready') return 'secondary';
  if (status === 'conflict') return 'destructive';
  return 'outline';
}

export default function QQCallbackStatusPanel({
  status,
  loading,
  error,
  onRetry,
}: QQCallbackStatusPanelProps) {
  const { t } = useTranslation();
  const callbackUrl = useMemo(() => {
    if (!status) return '';
    return `${window.location.origin}${status.callback_path}`;
  }, [status]);

  const copyCallbackUrl = async () => {
    try {
      await navigator.clipboard.writeText(callbackUrl);
      toast.success(t('idcQuery.callback.copySuccess'));
    } catch {
      toast.error(t('idcQuery.callback.copyError'));
    }
  };

  if (loading) {
    return (
      <PanelBody className="flex items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        {t('idcQuery.callback.loading')}
      </PanelBody>
    );
  }

  if (error || !status) {
    return (
      <PanelBody className="flex flex-col items-center justify-center gap-3 text-center">
        <AlertTriangle className="size-5 text-destructive" />
        <p className="max-w-md break-words text-sm text-muted-foreground">
          {t('idcQuery.callback.loadError')}
          {error ? `: ${error}` : ''}
        </p>
        <Button type="button" variant="outline" onClick={onRetry}>
          <RefreshCw />
          {t('idcQuery.retry')}
        </Button>
      </PanelBody>
    );
  }

  return (
    <PanelBody>
      <div className="mx-auto w-full max-w-3xl space-y-7">
        <section className="space-y-4 border-b pb-7">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              {status.status === 'ready' ? (
                <CheckCircle2 className="size-5 shrink-0 text-green-600" />
              ) : (
                <AlertTriangle className="size-5 shrink-0 text-destructive" />
              )}
              <h3 className="text-sm font-semibold">
                {t('idcQuery.callback.title')}
              </h3>
            </div>
            <Badge variant={statusVariant(status.status)}>
              {t(`idcQuery.callback.status.${status.status}`)}
            </Badge>
          </div>

          <div className="space-y-2">
            <label
              htmlFor="qqofficial-callback-url"
              className="text-sm font-medium"
            >
              {t('idcQuery.callback.url')}
            </label>
            <div className="flex min-w-0 items-center gap-2">
              <Input
                id="qqofficial-callback-url"
                value={callbackUrl}
                readOnly
                className="min-w-0 font-mono text-xs"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={copyCallbackUrl}
                aria-label={t('idcQuery.callback.copy')}
                title={t('idcQuery.callback.copy')}
              >
                <Copy />
              </Button>
            </div>
          </div>

          {status.configured_callback_url &&
            status.configured_callback_url !== callbackUrl && (
              <div className="min-w-0 text-xs text-muted-foreground">
                <span className="font-medium">
                  {t('idcQuery.callback.configuredUrl')}:{' '}
                </span>
                <span className="break-all font-mono">
                  {status.configured_callback_url}
                </span>
              </div>
            )}

          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border bg-border">
            <div className="bg-background px-3 py-3">
              <div className="text-xs text-muted-foreground">
                {t('idcQuery.callback.configuredBots')}
              </div>
              <div className="mt-1 text-lg font-semibold tabular-nums">
                {status.configured_bots}
              </div>
            </div>
            <div className="bg-background px-3 py-3">
              <div className="text-xs text-muted-foreground">
                {t('idcQuery.callback.activeWebhooks')}
              </div>
              <div className="mt-1 text-lg font-semibold tabular-nums">
                {status.active_webhook_bots}
              </div>
            </div>
          </div>
        </section>

        <section className="space-y-4">
          <div className="flex items-center gap-2">
            <RadioTower className="size-4" />
            <h3 className="text-sm font-semibold">
              {t('idcQuery.callback.bots')}
            </h3>
          </div>

          {status.bots.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              {t('idcQuery.callback.empty')}
            </p>
          ) : (
            <div className="divide-y border-y">
              {status.bots.map((bot) => (
                <article key={bot.uuid} className="space-y-4 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">
                        {bot.name || t('idcQuery.callback.unnamedBot')}
                      </div>
                      <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
                        {t('idcQuery.callback.appId')}: {bot.app_id || '-'}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Badge variant={bot.enabled ? 'secondary' : 'outline'}>
                        {t(
                          bot.enabled
                            ? 'idcQuery.callback.enabled'
                            : 'idcQuery.callback.disabled',
                        )}
                      </Badge>
                      <Badge variant="outline">
                        {t(`idcQuery.callback.mode.${bot.mode}`)}
                      </Badge>
                    </div>
                  </div>

                  {bot.metrics && (
                    <div className="grid grid-cols-2 gap-x-5 gap-y-3 text-xs sm:grid-cols-3">
                      <div>
                        <div className="text-muted-foreground">
                          {t('idcQuery.callback.lastEvent')}
                        </div>
                        <div className="mt-1 tabular-nums">
                          {formatTimestamp(bot.metrics.last_event_at || '')}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">
                          {t('idcQuery.callback.requests')}
                        </div>
                        <div className="mt-1 tabular-nums">
                          {bot.metrics.requests_total}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">
                          {t('idcQuery.callback.events')}
                        </div>
                        <div className="mt-1 tabular-nums">
                          {bot.metrics.events_total}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">
                          {t('idcQuery.callback.validations')}
                        </div>
                        <div className="mt-1 tabular-nums">
                          {bot.metrics.validations_total}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">
                          {t('idcQuery.callback.duplicates')}
                        </div>
                        <div className="mt-1 tabular-nums">
                          {bot.metrics.duplicates_total}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">
                          {t('idcQuery.callback.rejected')}
                        </div>
                        <div className="mt-1 tabular-nums">
                          {bot.metrics.rejected_total}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">
                          {t('idcQuery.callback.pending')}
                        </div>
                        <div className="mt-1 tabular-nums">
                          {bot.metrics.pending_events} /{' '}
                          {bot.metrics.pending_limit}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground">
                          {t('idcQuery.callback.overloaded')}
                        </div>
                        <div className="mt-1 tabular-nums">
                          {bot.metrics.overloaded_total}
                        </div>
                      </div>
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </PanelBody>
  );
}
