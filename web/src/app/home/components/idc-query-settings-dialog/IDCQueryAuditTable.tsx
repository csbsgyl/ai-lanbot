import { useTranslation } from 'react-i18next';
import { Activity, AlertTriangle, Loader2, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { IDCQueryAuditEvent } from '@/app/infra/entities/api';
import { PanelBody } from '@/app/home/components/settings-dialog/panel-layout';

interface IDCQueryAuditTableProps {
  events: IDCQueryAuditEvent[];
  generatedAt: string;
  loading: boolean;
  error: string;
  onRetry: () => void;
}

function maskIdentifier(value: string): string {
  if (!value) return '-';
  if (value.length <= 4) return '****';
  if (value.length <= 7) return `${value.slice(0, 1)}***${value.slice(-1)}`;
  return `${value.slice(0, 3)}***${value.slice(-2)}`;
}

function formatTimestamp(value: string): string {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function outcomeVariant(
  outcome: string,
): 'secondary' | 'outline' | 'destructive' {
  if (outcome === 'success') return 'secondary';
  if (outcome === 'denied') return 'outline';
  return 'destructive';
}

export default function IDCQueryAuditTable({
  events,
  generatedAt,
  loading,
  error,
  onRetry,
}: IDCQueryAuditTableProps) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <PanelBody className="flex items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        {t('idcQuery.audit.loading')}
      </PanelBody>
    );
  }

  if (error) {
    return (
      <PanelBody className="flex flex-col items-center justify-center gap-3 text-center">
        <AlertTriangle className="size-5 text-destructive" />
        <p className="max-w-md break-words text-sm text-muted-foreground">
          {t('idcQuery.audit.loadError')}: {error}
        </p>
        <Button type="button" variant="outline" onClick={onRetry}>
          <RefreshCw />
          {t('idcQuery.retry')}
        </Button>
      </PanelBody>
    );
  }

  if (events.length === 0) {
    return (
      <PanelBody className="flex flex-col items-center justify-center gap-3 text-center text-muted-foreground">
        <Activity className="size-6" />
        <p className="text-sm">{t('idcQuery.audit.empty')}</p>
      </PanelBody>
    );
  }

  return (
    <PanelBody className="space-y-3">
      <div className="text-xs text-muted-foreground">
        {t('idcQuery.audit.generatedAt', {
          time: formatTimestamp(generatedAt),
          count: events.length,
        })}
      </div>
      <div className="overflow-x-auto rounded-md border">
        <Table className="min-w-[760px] table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className="w-[170px]">
                {t('idcQuery.audit.time')}
              </TableHead>
              <TableHead className="w-[120px]">
                {t('idcQuery.audit.command')}
              </TableHead>
              <TableHead className="w-[150px]">
                {t('idcQuery.audit.result')}
              </TableHead>
              <TableHead className="w-[190px]">
                {t('idcQuery.audit.identity')}
              </TableHead>
              <TableHead className="w-[110px]">
                {t('idcQuery.audit.member')}
              </TableHead>
              <TableHead className="w-[80px] text-right">
                {t('idcQuery.audit.duration')}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.map((event, index) => (
              <TableRow key={`${event.timestamp}-${event.request_id}-${index}`}>
                <TableCell className="whitespace-nowrap text-xs tabular-nums">
                  {formatTimestamp(event.timestamp)}
                </TableCell>
                <TableCell className="font-medium">
                  {t(`idcQuery.audit.commands.${event.command}`, {
                    defaultValue: event.command,
                  })}
                </TableCell>
                <TableCell>
                  <div className="space-y-1">
                    <Badge variant={outcomeVariant(event.outcome)}>
                      {t(`idcQuery.audit.outcomes.${event.outcome}`, {
                        defaultValue: event.outcome,
                      })}
                    </Badge>
                    <div className="truncate text-xs text-muted-foreground">
                      {t(`idcQuery.audit.reasons.${event.reason}`, {
                        defaultValue: event.reason,
                      })}
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="space-y-1 text-xs font-mono">
                    <div className="truncate">
                      {t('idcQuery.audit.groupShort')}:{' '}
                      {maskIdentifier(event.group_id)}
                    </div>
                    <div className="truncate text-muted-foreground">
                      {t('idcQuery.audit.userShort')}:{' '}
                      {maskIdentifier(event.user_id)}
                    </div>
                  </div>
                </TableCell>
                <TableCell className="truncate font-mono text-xs">
                  {maskIdentifier(event.member_id)}
                </TableCell>
                <TableCell className="text-right text-xs tabular-nums">
                  {event.duration_ms} ms
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </PanelBody>
  );
}
