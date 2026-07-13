import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  CheckCircle2,
  CircleX,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import type {
  ApiRespIDCReadiness,
  IDCReadinessCheckStatus,
} from '@/app/infra/entities/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { PanelBody } from '@/app/home/components/settings-dialog/panel-layout';
import { formatTimestamp } from './display';

interface IDCReadinessPanelProps {
  readiness: ApiRespIDCReadiness | null;
  loading: boolean;
  error: string;
  onRetry: () => void;
}

function CheckIcon({ status }: { status: IDCReadinessCheckStatus }) {
  if (status === 'pass') {
    return <CheckCircle2 className="size-4 shrink-0 text-green-600" />;
  }
  if (status === 'fail') {
    return <CircleX className="size-4 shrink-0 text-destructive" />;
  }
  return <AlertTriangle className="size-4 shrink-0 text-amber-600" />;
}

function badgeVariant(
  status: IDCReadinessCheckStatus,
): 'secondary' | 'outline' | 'destructive' {
  if (status === 'fail') return 'destructive';
  if (status === 'pass') return 'secondary';
  return 'outline';
}

export default function IDCReadinessPanel({
  readiness,
  loading,
  error,
  onRetry,
}: IDCReadinessPanelProps) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <PanelBody className="flex items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        {t('idcQuery.readiness.loading')}
      </PanelBody>
    );
  }

  if (error || !readiness) {
    return (
      <PanelBody className="flex flex-col items-center justify-center gap-3 text-center">
        <AlertTriangle className="size-5 text-destructive" />
        <p className="max-w-md break-words text-sm text-muted-foreground">
          {t('idcQuery.readiness.loadError')}
          {error ? `: ${error}` : ''}
        </p>
        <Button type="button" variant="outline" onClick={onRetry}>
          <RefreshCw />
          {t('idcQuery.retry')}
        </Button>
      </PanelBody>
    );
  }

  const summaryStatus: IDCReadinessCheckStatus =
    readiness.status === 'ready'
      ? 'pass'
      : readiness.status === 'not_ready'
        ? 'fail'
        : 'warn';

  return (
    <PanelBody>
      <div className="mx-auto w-full max-w-3xl space-y-7">
        <section className="space-y-4 border-b pb-7">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <CheckIcon status={summaryStatus} />
              <h3 className="text-sm font-semibold">
                {t('idcQuery.readiness.title')}
              </h3>
            </div>
            <Badge variant={badgeVariant(summaryStatus)}>
              {t(`idcQuery.readiness.overall.${readiness.status}`)}
            </Badge>
          </div>

          <div className="grid gap-3 text-xs sm:grid-cols-3">
            <div>
              <div className="text-muted-foreground">
                {t('idcQuery.readiness.generatedAt')}
              </div>
              <div className="mt-1 tabular-nums">
                {formatTimestamp(readiness.generated_at)}
              </div>
            </div>
            <div>
              <div className="text-muted-foreground">
                {t('idcQuery.readiness.lastQQEvent')}
              </div>
              <div className="mt-1 tabular-nums">
                {readiness.last_qq_event_at
                  ? formatTimestamp(readiness.last_qq_event_at)
                  : t('idcQuery.readiness.never')}
              </div>
            </div>
            <div>
              <div className="text-muted-foreground">
                {t('idcQuery.readiness.lastIDCOperation')}
              </div>
              <div className="mt-1 tabular-nums">
                {readiness.last_idc_operation_at
                  ? formatTimestamp(readiness.last_idc_operation_at)
                  : t('idcQuery.readiness.never')}
              </div>
            </div>
          </div>
        </section>

        <section className="divide-y border-y">
          {readiness.checks.map((check) => (
            <div
              key={check.id}
              className="flex min-w-0 items-start justify-between gap-4 py-3"
            >
              <div className="flex min-w-0 items-start gap-3">
                <CheckIcon status={check.status} />
                <div className="min-w-0">
                  <div className="text-sm font-medium">
                    {t(`idcQuery.readiness.checks.${check.id}`)}
                  </div>
                  <div className="mt-1 break-words text-xs text-muted-foreground">
                    {t(`idcQuery.readiness.details.${check.code}`)}
                  </div>
                </div>
              </div>
              <Badge variant={badgeVariant(check.status)} className="shrink-0">
                {t(`idcQuery.readiness.status.${check.status}`)}
              </Badge>
            </div>
          ))}
        </section>
      </div>
    </PanelBody>
  );
}
