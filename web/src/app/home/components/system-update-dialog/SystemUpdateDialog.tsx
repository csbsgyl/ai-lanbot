import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertCircle,
  CheckCircle2,
  Download,
  LoaderCircle,
  RefreshCcw,
} from 'lucide-react';
import { toast } from 'sonner';

import { httpClient } from '@/app/infra/http/HttpClient';
import {
  ApiRespSystemUpdate,
  SystemUpdateState,
} from '@/app/infra/entities/api';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

const ACTIVE_STATES: SystemUpdateState[] = ['queued', 'checking', 'deploying'];

interface SystemUpdateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStatusChange?: (status: ApiRespSystemUpdate) => void;
}

function shortRevision(revision: string): string {
  return revision ? revision.slice(0, 8) : '-';
}

export default function SystemUpdateDialog({
  open,
  onOpenChange,
  onStatusChange,
}: SystemUpdateDialogProps) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<ApiRespSystemUpdate | null>(null);
  const [loading, setLoading] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);

  const publishStatus = useCallback(
    (nextStatus: ApiRespSystemUpdate) => {
      setStatus(nextStatus);
      onStatusChange?.(nextStatus);
    },
    [onStatusChange],
  );

  const loadStatus = useCallback(
    async (refresh: boolean, quiet: boolean = false) => {
      if (!quiet) setLoading(true);
      try {
        const nextStatus = await httpClient.getSystemUpdateStatus(refresh);
        publishStatus(nextStatus);
        setReconnecting(false);
      } catch {
        if (quiet) {
          setReconnecting(true);
        } else {
          toast.error(t('version.checkFailed'));
        }
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [publishStatus, t],
  );

  useEffect(() => {
    if (open) void loadStatus(true);
  }, [open, loadStatus]);

  const active = Boolean(status && ACTIVE_STATES.includes(status.state));
  useEffect(() => {
    if (!open || (!active && !reconnecting)) return;

    const timer = window.setInterval(() => {
      void loadStatus(false, true);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [active, loadStatus, open, reconnecting]);

  const statusText = useMemo(() => {
    if (loading && !status) return t('version.checking');
    if (reconnecting) return t('version.restarting');
    if (!status) return t('version.statusUnknown');
    if (status.state === 'queued') return t('version.queued');
    if (status.state === 'checking') return t('version.checking');
    if (status.state === 'deploying') return t('version.deploying');
    if (status.state === 'failed') return t('version.updateFailed');
    if (status.state === 'success' && !status.update_available) {
      return t('version.updateSuccess');
    }
    if (status.check_error) return t('version.checkFailed');
    return status.update_available
      ? t('version.updateAvailable')
      : t('version.upToDate');
  }, [loading, reconnecting, status, t]);

  const handleRequestUpdate = async () => {
    setConfirmOpen(false);
    setRequesting(true);
    try {
      const nextStatus = await httpClient.requestSystemUpdate();
      publishStatus(nextStatus);
      toast.success(t('version.updateQueued'));
    } catch (error) {
      const requestInterrupted =
        typeof error === 'object' &&
        error !== null &&
        'code' in error &&
        error.code === -1;
      if (requestInterrupted) {
        setReconnecting(true);
      } else {
        toast.error(t('version.updateFailed'));
      }
    } finally {
      setRequesting(false);
    }
  };

  const updateFinished = Boolean(
    status?.state === 'success' && !status.update_available,
  );

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>{t('version.updateCenter')}</DialogTitle>
            <DialogDescription>
              {status?.repository || 'csbsgyl/ai-lanbot'}
              {status?.branch ? ` / ${status.branch}` : ''}
            </DialogDescription>
          </DialogHeader>

          <div className="border-y divide-y text-sm">
            <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 py-3">
              <span className="text-muted-foreground">
                {t('version.currentRevision')}
              </span>
              <code className="font-mono text-xs">
                {shortRevision(status?.current_revision || '')}
              </code>
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 py-3">
              <span className="text-muted-foreground">
                {t('version.latestRevision')}
              </span>
              <code className="font-mono text-xs">
                {loading
                  ? t('version.checking')
                  : shortRevision(status?.latest_revision || '')}
              </code>
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 py-3">
              <span className="text-muted-foreground">
                {t('version.updateStatus')}
              </span>
              <span className="flex items-center gap-2 text-right">
                {active || reconnecting ? (
                  <LoaderCircle className="size-4 animate-spin" />
                ) : status?.state === 'failed' || status?.check_error ? (
                  <AlertCircle className="size-4 text-destructive" />
                ) : (
                  <CheckCircle2 className="size-4 text-emerald-600" />
                )}
                {statusText}
              </span>
            </div>
          </div>

          {status && !status.enabled && (
            <p className="text-sm text-muted-foreground">
              {t('version.automaticUnavailable')}
            </p>
          )}

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={() => void loadStatus(true)}
              disabled={loading || active || requesting}
            >
              <RefreshCcw className={loading ? 'animate-spin' : ''} />
              {t('version.checkForUpdates')}
            </Button>
            {updateFinished ? (
              <Button onClick={() => window.location.reload()}>
                <RefreshCcw />
                {t('version.reload')}
              </Button>
            ) : (
              <Button
                onClick={() => setConfirmOpen(true)}
                disabled={!status?.can_update || active || requesting}
              >
                {requesting || active ? (
                  <LoaderCircle className="animate-spin" />
                ) : (
                  <Download />
                )}
                {t('version.installUpdate')}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('version.confirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('version.confirmDescription')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={() => void handleRequestUpdate()}>
              {t('version.installUpdate')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
