import { useTranslation } from 'react-i18next';
import { AlertTriangle, Link2, Loader2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { IDCQueryBinding } from '@/app/infra/entities/api';
import { PanelBody } from '@/app/home/components/settings-dialog/panel-layout';
import { formatTimestamp, maskIdentifier } from './display';

interface IDCQueryBindingTableProps {
  bindings: IDCQueryBinding[];
  generatedAt: string;
  total: number;
  loading: boolean;
  error: string;
  onRetry: () => void;
}

export default function IDCQueryBindingTable({
  bindings,
  generatedAt,
  total,
  loading,
  error,
  onRetry,
}: IDCQueryBindingTableProps) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <PanelBody className="flex items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        {t('idcQuery.bindings.loading')}
      </PanelBody>
    );
  }

  if (error) {
    return (
      <PanelBody className="flex flex-col items-center justify-center gap-3 text-center">
        <AlertTriangle className="size-5 text-destructive" />
        <p className="max-w-md break-words text-sm text-muted-foreground">
          {t('idcQuery.bindings.loadError')}: {error}
        </p>
        <Button type="button" variant="outline" onClick={onRetry}>
          <RefreshCw />
          {t('idcQuery.retry')}
        </Button>
      </PanelBody>
    );
  }

  if (bindings.length === 0) {
    return (
      <PanelBody className="flex flex-col items-center justify-center gap-3 text-center text-muted-foreground">
        <Link2 className="size-6" />
        <p className="text-sm">{t('idcQuery.bindings.empty')}</p>
      </PanelBody>
    );
  }

  return (
    <PanelBody className="space-y-3">
      <div className="text-xs text-muted-foreground">
        {t('idcQuery.bindings.generatedAt', {
          time: formatTimestamp(generatedAt),
          count: bindings.length,
          total,
        })}
      </div>
      <div className="overflow-x-auto rounded-md border">
        <Table className="min-w-[720px] table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className="w-[170px]">
                {t('idcQuery.bindings.boundAt')}
              </TableHead>
              <TableHead className="w-[220px]">
                {t('idcQuery.bindings.customer')}
              </TableHead>
              <TableHead className="w-[160px]">
                {t('idcQuery.bindings.group')}
              </TableHead>
              <TableHead className="w-[160px]">
                {t('idcQuery.bindings.boundBy')}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {bindings.map((binding) => (
              <TableRow key={`${binding.group_id}-${binding.bound_at}`}>
                <TableCell className="whitespace-nowrap text-xs tabular-nums">
                  {formatTimestamp(binding.bound_at)}
                </TableCell>
                <TableCell>
                  <div className="space-y-1">
                    <div className="truncate font-medium">
                      {binding.member_name || t('idcQuery.bindings.unnamed')}
                    </div>
                    <div className="truncate font-mono text-xs text-muted-foreground">
                      {maskIdentifier(binding.member_id)}
                    </div>
                  </div>
                </TableCell>
                <TableCell className="truncate font-mono text-xs">
                  {maskIdentifier(binding.group_id)}
                </TableCell>
                <TableCell className="truncate font-mono text-xs">
                  {maskIdentifier(binding.bound_by)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </PanelBody>
  );
}
