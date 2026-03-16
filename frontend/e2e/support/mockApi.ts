import type { Page, Route } from '@playwright/test'

type JsonValue = Record<string, unknown> | unknown[]

const nowIso = '2026-03-16T10:00:00Z'

const sampleArtifact = {
  artifact_id: 'artifact-demo-001',
  task_id: 'task-demo-001',
  kind: 'manifest',
  path: 'data/tasks/task-demo-001/artifacts/deployment-demo.yaml',
  preview: 'deployment-demo.yaml',
  size_bytes: 256,
  created_at: nowIso,
}

const sampleTask = {
  task_id: 'task-demo-001',
  task_type: 'recommendation_generation',
  status: 'WAITING_CONFIRM',
  current_stage: 'WAITING_CONFIRM',
  progress: 90,
  progress_message: '建议草稿已生成，等待审批',
  trace_id: 'trace-demo-001',
  payload: { incident_id: 'incident-demo-001' },
  result_ref: {
    incident_id: 'incident-demo-001',
    guardrail_summary: {
      total: 1,
      fallback_count: 0,
      retried_count: 1,
      schema_error_count: 0,
      has_degraded: false,
    },
  },
  error: null,
  approval: null,
  created_at: nowIso,
  updated_at: nowIso,
  completed_at: null,
}

const sampleRecommendation = {
  recommendation_id: 'rec-demo-001',
  incident_id: 'incident-demo-001',
  target_asset_id: 'container/demo',
  kind: 'resource_tuning',
  confidence: 0.82,
  observation: '请求高峰与 CPU 使用率同步抬升。',
  recommendation: '建议先扩容 1 副本并观察 10 分钟。',
  risk_note: '扩容可能增加资源成本。',
  artifact_refs: [sampleArtifact],
  created_at: nowIso,
  updated_at: nowIso,
}

const sampleIncident = {
  incident_id: 'incident-demo-001',
  title: '入口 5xx 比例上升',
  severity: 'warning',
  status: 'open',
  service_key: 'demo/service-a',
  summary: '最近 10 分钟 5xx 明显升高。',
  confidence: 0.74,
  reasoning_tags: ['traffic_spike', 'cpu_hotspot'],
  recommended_actions: ['核查上游依赖', '评估临时扩容'],
  evidence_refs: [
    {
      evidence_id: 'ev-log-001',
      layer: 'traffic',
      type: 'log',
      source_type: 'log_snippet',
      title: '5xx 错误样本',
      summary: '同一路径在短时间内集中出现 502。',
      metric: '5xx_rate',
      value: 6.2,
      unit: '%',
      priority: 90,
      signal_strength: 'high',
      source_ref: {
        timestamp: nowIso,
        path: '/api/pay',
        status: 502,
        service_key: 'demo/service-a',
      },
      tags: ['nginx', 'error'],
      service_key: 'demo/service-a',
    },
  ],
  related_asset_ids: ['container/demo-a-1'],
  time_window_start: '2026-03-16T09:00:00Z',
  time_window_end: '2026-03-16T10:00:00Z',
  created_at: nowIso,
  updated_at: nowIso,
}

const jsonReply = (payload: JsonValue, status = 200) => ({
  status,
  headers: {
    'content-type': 'application/json; charset=utf-8',
  },
  body: JSON.stringify(payload),
})

const fulfillJson = async (route: Route, payload: JsonValue, status = 200) =>
  route.fulfill(jsonReply(payload, status))

const pathnameOf = (url: string) => new URL(url).pathname

// 主链路 smoke 只关注页面可渲染，这里统一兜底 API 数据，避免依赖外部环境。
export const registerApiMocks = async (page: Page) => {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const method = request.method().toUpperCase()
    const path = pathnameOf(request.url())

    if (method === 'GET' && path === '/api/dashboard/overview') {
      return fulfillJson(route, {
        cards: [
          { key: 'incident', label: '活跃异常', value: 1, status: 'warning' },
          { key: 'error_rate', label: '今日错误率', value: 2.4, unit: '%', status: 'warning' },
        ],
        traffic_trend: [
          { timestamp: '09:00', value: 120 },
          { timestamp: '10:00', value: 160 },
        ],
        recent_incidents: [sampleIncident],
        hot_services: [{ service_key: 'demo/service-a', score: 82, reason: '流量上升', metric_value: 82 }],
        data_health: { status: 'ready', title: '数据源就绪', message: '', degradation_reasons: [] },
        data_sources: {
          docker: { enabled: true, configured: true, status: 'ready', message: 'ok' },
          prometheus: { enabled: true, configured: true, status: 'ready', message: 'ok' },
        },
      })
    }

    if (method === 'GET' && path === '/api/traffic/summary') {
      return fulfillJson(route, {
        total_requests: 1024,
        page_views: 980,
        error_rate: 2.4,
        avg_latency: 0.12,
        top_paths: [{ path: '/api/pay', count: 120 }],
        hot_paths: [{ path: '/api/pay', count: 120, error_count: 8, error_rate: 6.67, avg_latency: 0.23 }],
        top_ips: [{ ip: '10.0.0.1', count: 44 }],
        hot_ips: [{ ip: '10.0.0.1', count: 44, error_count: 4, error_rate: 9.1, avg_latency: 0.3, sample_path: '/api/pay', geo_label: 'CN' }],
        status_distribution: [{ status: '200', count: 940 }, { status: '502', count: 24 }],
        geo_distribution: [{ name: 'CN', count: 800 }],
        ua_distribution: [{ name: 'Chrome', count: 700 }],
        trend: [{ timestamp: '09:00', requests: 120, errors: 2 }, { timestamp: '10:00', requests: 160, errors: 4 }],
        error_samples: [
          {
            timestamp: nowIso,
            method: 'GET',
            path: '/api/pay',
            status: 502,
            latency_ms: 220,
            client_ip: '10.0.0.1',
            geo_label: 'CN',
            user_agent: 'Mozilla/5.0',
            browser: 'Chrome',
            os: 'Windows',
            device: 'desktop',
            service_key: 'demo/service-a',
          },
        ],
        records_sample: [{ service_key: 'demo/service-a' }],
        data_status: 'ready',
        data_message: '',
        degradation_reasons: [],
        load_stats: {
          configured_paths: 1,
          scanned_files: 1,
          missing_files: 0,
          unreadable_files: 0,
          lines_read: 100,
          parsed_lines: 100,
          matched_records: 80,
          parse_failures: 0,
          enrich_failures: 0,
          time_filtered: 20,
          service_filtered: 0,
        },
      })
    }

    if (method === 'GET' && path === '/api/resources/summary') {
      return fulfillJson(route, {
        host: {
          cpu: { usage_percent: 58.2 },
          memory: { usage_percent: 66.1 },
        },
        alerts: [],
        containers: {
          available: true,
          items: [
            {
              asset_id: 'container/demo-a-1',
              name: 'demo-a-1',
              service_key: 'demo/service-a',
              status: 'running',
              restarts: 1,
              oom_killed: false,
            },
          ],
        },
        prometheus: { available: true, metrics: {} },
        hotspots: [],
        hotspot_layers: {
          host: [],
          container: [
            {
              name: 'demo-a-1',
              type: 'container',
              layer: 'container',
              score: 82,
              severity: 'high',
              category: 'cpu',
              reason: 'CPU 使用率偏高',
              explanation: '最近窗口 CPU 峰值接近阈值。',
              recommended_action: '观察并准备扩容',
              metric: 'cpu_usage',
              value: 82,
              unit: '%',
              service_key: 'demo/service-a',
            },
          ],
          pod: [],
          service: [],
          other: [],
        },
        hotspot_summary: {
          total: 1,
          layers: { host: 0, container: 1, pod: 0, service: 0, other: 0 },
          severities: { critical: 0, high: 1, medium: 0 },
          categories: { cpu: 1 },
          top_services: [{ service_key: 'demo/service-a', count: 1, top_score: 82 }],
        },
        risk_summary: {
          total: 1,
          levels: { critical: 0, high: 1, medium: 0 },
          oom: { total: 0, critical: 0, high: 0, medium: 0 },
          restart: { total: 1, critical: 0, high: 1, medium: 0 },
        },
        risk_items: [
          {
            risk_id: 'risk-demo-001',
            risk_type: 'restart',
            level: 'high',
            layer: 'container',
            target: 'demo-a-1',
            service_key: 'demo/service-a',
            metric: 'restart_count',
            value: 1,
            unit: '次',
            evidence: '10 分钟内出现重启',
            source: 'docker',
          },
        ],
        source_health: {
          docker: { configured: true, status: 'ready', message: 'ok' },
          prometheus: { configured: true, status: 'ready', message: 'ok' },
        },
        data_status: 'ready',
        data_message: '',
        degradation_reasons: [],
      })
    }

    if (method === 'GET' && path === '/api/assets') {
      return fulfillJson(route, {
        items: [
          {
            asset_id: 'container/demo-a-1',
            asset_type: 'container',
            name: 'demo-a-1',
            service_key: 'demo/service-a',
            unmapped: false,
          },
        ],
        total: 1,
        synced: 1,
      })
    }

    if (method === 'GET' && path === '/api/incidents') {
      return fulfillJson(route, { items: [sampleIncident], total: 1 })
    }

    if (method === 'GET' && /^\/api\/incidents\/[^/]+$/.test(path)) {
      return fulfillJson(route, {
        incident: sampleIncident,
        recommendations: [sampleRecommendation],
        log_samples: [],
        evidence_summary: {
          total: 1,
          layers: { traffic: 1 },
          primary_layer: 'traffic',
          headline: '流量层证据最强',
          next_step: '建议查看草稿并确认',
          reasoning_tags: ['traffic_spike'],
          highlights: sampleIncident.evidence_refs,
          summary_lines: ['5xx 在 /api/pay 路径集中出现'],
        },
        recommendation_task: {
          ...sampleTask,
          artifact_ready: true,
          artifact_count: 1,
          recommendation_count: 1,
          recommendation_ids: ['rec-demo-001'],
        },
      })
    }

    if (method === 'POST' && path === '/api/incidents/analyze') {
      return fulfillJson(route, { ...sampleTask, task_id: 'task-incident-001', task_type: 'incident_analysis' })
    }

    if (method === 'POST' && /^\/api\/incidents\/[^/]+\/ai-summary$/.test(path)) {
      return fulfillJson(route, {
        incident_id: 'incident-demo-001',
        provider: 'qwen3.5-plus',
        summary: '流量异常与资源热点具备相关性。',
        risk_level: 'medium',
        confidence: 0.77,
        primary_causes: ['入口请求突增'],
        recommended_actions: ['先扩容后观察'],
        evidence_citations: ['ev-log-001'],
        parse_mode: 'structured',
        log_sample_count: 1,
        recommendation_count: 1,
      })
    }

    if (method === 'POST' && path === '/api/recommendations/generate') {
      return fulfillJson(route, sampleTask)
    }

    if (method === 'GET' && /^\/api\/recommendations\/[^/]+$/.test(path)) {
      return fulfillJson(route, {
        ...sampleRecommendation,
        evidence_refs: [
          {
            evidence_id: 'ev-artifact-001',
            source_type: 'artifact',
            title: '任务产物',
            summary: '建议草稿来自当前任务产物',
            quote: 'resources.requests.cpu: 300m -> 500m',
            artifact_ref: sampleArtifact,
            jump: { kind: 'artifact', task_id: sampleArtifact.task_id, artifact_id: sampleArtifact.artifact_id },
          },
        ],
        log_samples: [],
        evidence_status: 'sufficient',
        evidence_message: '证据充足',
        confidence_effective: 0.82,
        recommendation_effective: sampleRecommendation.recommendation,
        evidence_summary: { total: 1, artifact: 1, log_snippet: 0, metric_snapshot: 0, incident_evidence: 0 },
        artifact_views: {
          primary_view: 'recommended',
          available_views: ['baseline', 'recommended', 'diff'],
          baseline: {
            view_key: 'baseline',
            label: '基线',
            filename: 'baseline.yaml',
            kind: 'manifest',
            artifact_id: 'artifact-baseline-001',
            task_id: sampleArtifact.task_id,
            summary: '变更前配置',
          },
          recommended: {
            view_key: 'recommended',
            label: '建议',
            filename: 'recommended.yaml',
            kind: 'manifest',
            artifact_id: sampleArtifact.artifact_id,
            task_id: sampleArtifact.task_id,
            summary: '变更后配置',
          },
          diff: {
            view_key: 'diff',
            label: '差异',
            filename: 'changes.diff',
            kind: 'diff',
            artifact_id: 'artifact-diff-001',
            task_id: sampleArtifact.task_id,
            summary: '行级差异',
            added_lines: 5,
            removed_lines: 1,
            hunk_count: 2,
            total_changed_lines: 6,
          },
          risk_summary: {
            level: 'medium',
            score: 62,
            review_required: true,
            highlights: ['涉及资源配额调整'],
          },
          change_stats: {
            total_changed_lines: 6,
            change_level: 'medium',
            added_lines: 5,
            removed_lines: 1,
            hunk_count: 2,
          },
        },
        feedback_summary: { adopt: 1, reject: 0, rewrite: 0 },
        feedback_items: [
          {
            feedback_id: 'feedback-demo-001',
            recommendation_id: sampleRecommendation.recommendation_id,
            incident_id: sampleIncident.incident_id,
            task_id: sampleTask.task_id,
            action: 'adopt',
            reason_code: 'confirmed',
            comment: '建议合理',
            operator: 'tester',
            created_at: nowIso,
          },
        ],
        task_context: {
          task_id: sampleTask.task_id,
          task_type: sampleTask.task_type,
          status: sampleTask.status,
          current_stage: sampleTask.current_stage,
          progress: sampleTask.progress,
          progress_message: sampleTask.progress_message,
          created_at: sampleTask.created_at,
          updated_at: sampleTask.updated_at,
          completed_at: sampleTask.completed_at,
          approval: sampleTask.approval,
        },
        task_trace_preview: [{ step: 'collect', observation: { summary: '收集完成' } }],
        task_trace_summary: {
          total_steps: 1,
          last_step: { step: 'collect', action: 'fetch', stage: 'COLLECTING', summary: '收集完成', created_at: nowIso },
        },
      })
    }

    if (method === 'GET' && /^\/api\/recommendations\/[^/]+\/feedback$/.test(path)) {
      return fulfillJson(route, {
        recommendation_id: sampleRecommendation.recommendation_id,
        summary: { adopt: 1, reject: 0, rewrite: 0 },
        items: [],
      })
    }

    if (method === 'POST' && /^\/api\/recommendations\/[^/]+\/feedback$/.test(path)) {
      return fulfillJson(route, {
        item: {
          feedback_id: 'feedback-demo-002',
          recommendation_id: sampleRecommendation.recommendation_id,
          incident_id: sampleIncident.incident_id,
          task_id: sampleTask.task_id,
          action: 'rewrite',
          reason_code: 'need_adjust',
          comment: '请调整阈值',
          operator: 'tester',
          created_at: nowIso,
        },
        summary: { adopt: 1, reject: 0, rewrite: 1 },
      })
    }

    if (method === 'POST' && /^\/api\/recommendations\/[^/]+\/ai-review$/.test(path)) {
      return fulfillJson(route, {
        recommendation_id: sampleRecommendation.recommendation_id,
        incident_id: sampleIncident.incident_id,
        provider: 'qwen3.5-plus',
        summary: '建议可执行，但需关注成本变化。',
        risk_level: 'medium',
        confidence: 0.8,
        risk_assessment: '中风险',
        rollback_plan: ['回滚至 baseline'],
        validation_checks: ['观察错误率'],
        evidence_citations: ['ev-artifact-001'],
        parse_mode: 'structured',
      })
    }

    if (method === 'GET' && path === '/api/tasks') {
      return fulfillJson(route, { items: [sampleTask], total: 1 })
    }

    if (method === 'GET' && /^\/api\/tasks\/[^/]+$/.test(path)) {
      return fulfillJson(route, {
        task: sampleTask,
        trace_preview: [{ step: 'collect', observation: { summary: '收集完成' } }],
        artifacts: [sampleArtifact],
        failure_diagnosis: null,
      })
    }

    if (method === 'GET' && /^\/api\/tasks\/[^/]+\/artifacts$/.test(path)) {
      return fulfillJson(route, {
        items: [sampleArtifact],
        total: 1,
        filtered: 1,
        kind: '',
        query: '',
        group_by: 'kind',
        groups: [{ group_key: 'manifest', count: 1, items: [sampleArtifact] }],
      })
    }

    if (method === 'GET' && /^\/api\/tasks\/[^/]+\/diagnosis$/.test(path)) {
      return fulfillJson(route, {
        task_id: sampleTask.task_id,
        status: 'FAILED',
        retryable: true,
        error: {
          error_code: 'MOCK_ERROR',
          error_message: 'mock failure',
          failed_stage: 'ANALYZING',
        },
        trace_stats: {
          total_steps: 1,
          stages: { ANALYZING: 1 },
          last_step: {
            step: 'analyze',
            action: 'detect',
            stage: 'ANALYZING',
            summary: 'mock',
            created_at: nowIso,
          },
        },
        artifact_count: 1,
        artifact_hints: ['deployment-demo.yaml'],
        possible_causes: ['mock'],
        suggested_actions: ['retry'],
      })
    }

    if (method === 'GET' && /^\/api\/tasks\/[^/]+\/artifacts\/[^/]+\/content$/.test(path)) {
      return fulfillJson(route, {
        artifact: sampleArtifact,
        filename: 'deployment-demo.yaml',
        content: 'apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: demo-a\n',
        content_type: 'text/yaml',
      })
    }

    if (method === 'POST' && /^\/api\/tasks\/[^/]+\/approve$/.test(path)) {
      return fulfillJson(route, { success: true })
    }

    if (method === 'POST' && /^\/api\/tasks\/[^/]+\/cancel$/.test(path)) {
      return fulfillJson(route, { success: true })
    }

    if (method === 'GET' && path === '/api/metrics/recommendation') {
      return fulfillJson(route, {
        start_date: '2026-03-10',
        end_date: '2026-03-16',
        service_key: '',
        provider_name: '',
        model: '',
        version: '',
        summary: {
          feedback_total: 4,
          adopt: 3,
          reject: 1,
          rewrite: 0,
          adopt_rate: 75,
          reject_rate: 25,
          rewrite_rate: 0,
          feedback_bound_task: 4,
          feedback_unbound_task: 0,
          feedback_bound_rate: 100,
          task_total: 6,
          task_success: 5,
          task_failed: 1,
          task_approved: 3,
          task_approval_rate: 50,
          task_success_rate: 83.3,
          avg_task_duration_ms: 4200,
        },
        trend: [],
        service_breakdown: [],
        provider_breakdown: [],
        model_breakdown: [],
        version_breakdown: [],
      })
    }

    if (method === 'GET' && path === '/api/metrics/ai-usage') {
      return fulfillJson(route, {
        start_date: '2026-03-10',
        end_date: '2026-03-16',
        service_key: '',
        provider_name: '',
        model: '',
        version: '',
        summary: {
          ai_call_total: 12,
          ai_error_count: 1,
          ai_success_count: 11,
          ai_timeout_count: 0,
          ai_error_rate: 8.3,
          ai_timeout_rate: 0,
          guardrail_fallback_count: 1,
          guardrail_retried_count: 2,
          guardrail_schema_error_count: 0,
          guardrail_fallback_rate: 8.3,
          guardrail_schema_error_rate: 0,
          ai_avg_latency_ms: 1200,
          ai_total_tokens: 8000,
          ai_total_cost: 1.2,
          ai_cost_per_call: 0.1,
        },
        trend: [],
        service_breakdown: [],
        model_breakdown: [],
        provider_breakdown: [],
        version_breakdown: [],
        records_count: 12,
      })
    }

    if (method === 'GET' && path === '/api/executors/status') {
      return fulfillJson(route, {
        plugins: [
          {
            plugin_key: 'linux',
            display_name: 'Linux 只读',
            description: '用于基础系统只读排查',
            enabled: true,
            readonly_only: true,
            write_enabled: false,
            failure_count: 0,
            circuit_open_until: null,
            circuit_remaining_seconds: 0,
            last_error: '',
            health_status: 'healthy',
            readonly_examples: ['ps aux', 'df -h'],
            write_examples: [],
            readonly_categories: [{ category_key: 'system', category_label: '系统', count: 2 }],
            readonly_command_packs: [
              {
                template_id: 'linux-ps',
                category_key: 'system',
                category_label: '系统',
                title: '进程列表',
                description: '查看进程',
                command: 'ps aux',
              },
            ],
            updated_at: nowIso,
          },
        ],
        recent_logs: [],
        recent_failures: [],
        recent_limit: 30,
        summary: {
          total: 1,
          enabled: 1,
          degraded: 0,
          success: 3,
          error: 0,
          timeout: 0,
          rejected: 0,
          circuit_open: 0,
          approval_required: 0,
          circuit_open_plugins: 0,
          top_error_codes: [],
        },
      })
    }

    if (method === 'POST' && path === '/api/executors/run') {
      return fulfillJson(route, {
        execution: {
          execution_id: 'exec-demo-001',
          task_id: null,
          plugin_key: 'linux',
          command: 'ps aux',
          readonly: true,
          status: 'success',
          exit_code: 0,
          stdout_preview: 'root  1 ...',
          stderr_preview: '',
          duration_ms: 60,
          error_code: '',
          error_message: '',
          operator: 'tester',
          approval_ticket: '',
          created_at: nowIso,
        },
        plugin: {
          plugin_key: 'linux',
          display_name: 'Linux 只读',
          description: '用于基础系统只读排查',
          enabled: true,
          readonly_only: true,
          write_enabled: false,
          failure_count: 0,
          circuit_open_until: null,
          circuit_remaining_seconds: 0,
          last_error: '',
          health_status: 'healthy',
          readonly_examples: ['ps aux'],
          write_examples: [],
          readonly_categories: [],
          readonly_command_packs: [],
          updated_at: nowIso,
        },
      })
    }

    if (method === 'PATCH' && /^\/api\/executors\/plugins\/[^/]+$/.test(path)) {
      return fulfillJson(route, { success: true })
    }

    if (method === 'GET' && path === '/api/ai/providers') {
      return fulfillJson(route, {
        providers: [
          {
            provider_id: 'provider-demo-001',
            name: 'qwen3.5-plus',
            type: 'openai_compatible',
            model: 'qwen3.5-plus',
            base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            enabled: true,
            is_default: true,
            timeout: 30,
            max_retries: 2,
            api_key_configured: true,
          },
        ],
      })
    }

    return fulfillJson(route, {})
  })
}

