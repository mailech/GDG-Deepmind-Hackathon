'use client';

import type { AppConfig } from '@/app-config';
import { NovaView } from '@/components/nova/nova-view';

interface ViewControllerProps {
  appConfig: AppConfig;
}

/**
 * Day 3: the starter's two-view flow (welcome / session) is replaced by
 * NovaView, which models all five required states explicitly — ready,
 * connecting, live, ended, and microphone-error.
 */
export function ViewController(_props: ViewControllerProps) {
  return <NovaView />;
}
