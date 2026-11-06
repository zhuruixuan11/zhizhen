<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SyndromeReport } from '@/types'
import { ElMessage } from 'element-plus'
import { ArrowDown, DocumentCopy } from '@element-plus/icons-vue'
import GraphRefCard from './GraphRefCard.vue'
import KnowledgeGraphView from './KnowledgeGraphView.vue'
import DisclaimerBar from './DisclaimerBar.vue'
import { createShareLink, exportReport } from '@/api/modules'

const showGraph = ref(false)
const shareDialog = ref(false)
const shareUrl = ref('')
const shareExpires = ref('')
const shareLoading = ref(false)
const exportLoading = ref<'json' | 'pdf' | null>(null)

const props = defineProps<{
  report: SyndromeReport
  sessionId?: number
}>()

const hasSession = computed(() => props.sessionId != null)

async function openShare() {
  if (!props.sessionId) return
  shareLoading.value = true
  try {
    const data = await createShareLink(props.sessionId)
    const origin = window.location.origin
    shareUrl.value = `${origin}/share/${data.token}`
    shareExpires.value = data.expires_at
    shareDialog.value = true
  } catch {
    // 错误由 http 拦截器统一提示
  } finally {
    shareLoading.value = false
  }
}

async function copyShareUrl() {
  try {
    await navigator.clipboard.writeText(shareUrl.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动复制')
  }
}

async function doExport(fmt: 'json' | 'pdf') {
  if (!props.sessionId) return
  exportLoading.value = fmt
  try {
    await exportReport(props.sessionId, fmt)
    ElMessage.success(`报告已导出为 ${fmt.toUpperCase()}`)
  } catch {
    // 错误由拦截器提示
  } finally {
    exportLoading.value = null
  }
}

const riskText: Record<string, string> = {
  low: '低风险',
  medium: '中等风险',
  high: '高风险 · 建议就医',
  emergency: '急危重症 · 请立即就医',
}

const riskType: Record<string, 'success' | 'warning' | 'danger'> = {
  low: 'success',
  medium: 'warning',
  high: 'danger',
  emergency: 'danger',
}

const isEmergency = computed(() => props.report.risk_level === 'emergency')

const confidencePercent = computed(() => {
  const c = props.report.confidence
  if (c == null) return null
  return c <= 1 ? Math.round(c * 100) : Math.round(c)
})

function weightPercent(weight: number): string {
  return weight <= 1 ? `${Math.round(weight * 100)}%` : `${Math.round(weight)}%`
}
</script>

<template>
  <div class="syndrome-report">
    <!-- 急危重症引导（仅含必要字段） -->
    <el-alert
      v-if="isEmergency"
      type="error"
      :closable="false"
      show-icon
      class="emergency-alert"
    >
      <template #title>
        <div class="emergency-title">⚠ 疑似急危重症，请立即前往正规医疗机构就诊</div>
      </template>
      <template #default>
        <p v-if="report.syndrome" class="emergency-syndrome">{{ report.syndrome }}</p>
        <ul v-if="report.lifestyle_advice?.length" class="emergency-advice">
          <li v-for="(item, i) in report.lifestyle_advice" :key="i">{{ item }}</li>
        </ul>
      </template>
    </el-alert>

    <!-- 常规辨证报告 -->
    <template v-else>
      <div class="report-header">
        <div class="syndrome-main">
          <div class="syndrome-label">辨证证型</div>
          <div class="syndrome-name">{{ report.syndrome || '—' }}</div>
        </div>
        <div class="header-meta">
          <el-tag :type="riskType[report.risk_level] ?? 'info'" effect="dark" size="large">
            {{ riskText[report.risk_level] ?? report.risk_level }}
          </el-tag>
          <el-tag v-if="confidencePercent != null" type="primary" effect="plain" size="large">
            置信度 {{ confidencePercent }}%
          </el-tag>
        </div>
      </div>

      <!-- 操作栏：分享 / 导出 -->
      <div v-if="hasSession" class="action-bar">
        <el-button type="primary" :loading="shareLoading" @click="openShare">
          🔗 分享报告
        </el-button>
        <el-dropdown trigger="click" @command="doExport" :disabled="exportLoading !== null">
          <el-button :loading="exportLoading !== null">
            📥 导出报告
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="json">
                <span>导出 JSON</span>
              </el-dropdown-item>
              <el-dropdown-item command="pdf">
                <span>导出 PDF</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>

      <section class="report-section">
        <h3 class="section-title">辨证依据链</h3>
        <template v-if="report.evidence?.length">
          <div v-for="(ev, i) in report.evidence" :key="i" class="evidence-item">
            <div class="evidence-source">
              <el-tag size="small" effect="plain">{{ ev.source }}</el-tag>
              <span class="evidence-weight">权重 {{ weightPercent(ev.weight) }}</span>
            </div>
            <p class="evidence-desc">{{ ev.description }}</p>
          </div>
        </template>
        <p v-else class="section-empty">暂无依据数据</p>
      </section>

      <section v-if="report.differential?.length" class="report-section">
        <h3 class="section-title">鉴别诊断</h3>
        <ul class="plain-list">
          <li v-for="(d, i) in report.differential" :key="i">{{ d }}</li>
        </ul>
      </section>

      <section v-if="report.treatment_principle" class="report-section">
        <h3 class="section-title">治疗原则</h3>
        <p class="section-text">{{ report.treatment_principle }}</p>
      </section>

      <section v-if="report.formula_suggestions?.length" class="report-section">
        <h3 class="section-title">经典方剂科普</h3>
        <el-collapse accordion>
          <el-collapse-item v-for="(f, i) in report.formula_suggestions" :key="i" :name="i">
            <template #title>
              <div class="formula-title">
                <span class="formula-name">{{ f.name }}</span>
                <span class="formula-source">《{{ f.source }}》</span>
              </div>
            </template>
            <div class="formula-body">
              <p v-if="f.effects?.length" class="formula-line">
                <span class="f-label">功效：</span>{{ f.effects.join('、') }}
              </p>
              <p v-if="f.indications?.length" class="formula-line">
                <span class="f-label">主治：</span>{{ f.indications.join('、') }}
              </p>
              <p v-if="f.contraindications" class="formula-line">
                <span class="f-label">禁忌：</span>{{ f.contraindications }}
              </p>
              <p v-if="f.dosage_note" class="formula-line">
                <span class="f-label">剂量说明：</span>{{ f.dosage_note }}
              </p>
              <p v-if="f.note" class="formula-note">{{ f.note }}</p>
              <p class="formula-warning">以上方剂仅作经典成方科普，请勿自行抓药服用。</p>
            </div>
          </el-collapse-item>
        </el-collapse>
      </section>

      <section v-if="report.diet_advice?.length" class="report-section">
        <h3 class="section-title">饮食调养</h3>
        <ul class="plain-list">
          <li v-for="(d, i) in report.diet_advice" :key="i">{{ d }}</li>
        </ul>
      </section>

      <section v-if="report.acupoint_advice?.length" class="report-section">
        <h3 class="section-title">穴位调护</h3>
        <ul class="plain-list">
          <li v-for="(a, i) in report.acupoint_advice" :key="i">{{ a }}</li>
        </ul>
      </section>

      <section v-if="report.lifestyle_advice?.length" class="report-section">
        <h3 class="section-title">生活调养</h3>
        <ul class="plain-list">
          <li v-for="(l, i) in report.lifestyle_advice" :key="i">{{ l }}</li>
        </ul>
      </section>

      <section v-if="report.graph_refs?.length" class="report-section">
        <div class="section-head">
          <h3 class="section-title">知识图谱依据</h3>
          <el-button link type="primary" size="small" @click="showGraph = !showGraph">
            {{ showGraph ? '收起推导图' : '查看推导图' }}
          </el-button>
        </div>
        <KnowledgeGraphView v-if="showGraph" :report="report" />
        <div v-else class="graph-grid">
          <GraphRefCard
            v-for="(ref, i) in report.graph_refs"
            :key="i"
            :graph-ref="ref"
          />
        </div>
      </section>
    </template>

    <div class="report-disclaimer">
      <DisclaimerBar :text="report.disclaimer || undefined" />
    </div>

    <!-- 分享弹窗 -->
    <el-dialog
      v-model="shareDialog"
      title="分享辨证报告"
      width="480px"
      :close-on-click-modal="false"
    >
      <div class="share-content">
        <p class="share-tip">复制以下链接发送给亲友或医生，对方可查看您的辨证报告（无需登录）。</p>
        <el-input
          v-model="shareUrl"
          readonly
          size="large"
        >
          <template #append>
            <el-button :icon="DocumentCopy" @click="copyShareUrl">复制</el-button>
          </template>
        </el-input>
        <p class="share-expire">
          🔒 链接有效期至 <strong>{{ shareExpires }}</strong>，过期后需重新生成。
        </p>
      </div>
      <template #footer>
        <el-button @click="shareDialog = false">关闭</el-button>
        <el-button type="primary" :icon="DocumentCopy" @click="copyShareUrl">
          复制链接
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.syndrome-report {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.emergency-alert {
  --el-alert-bg-color: rgba(200, 81, 63, 0.14);
  border-color: rgba(200, 81, 63, 0.5);
  border-radius: 12px;
}

.emergency-title {
  font-size: 17px;
  font-weight: 700;
}

.emergency-syndrome {
  margin: 8px 0;
  font-size: 15px;
}

.emergency-advice {
  margin: 8px 0;
  padding-left: 20px;
  line-height: 1.8;
}

.report-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 20px;
  background: linear-gradient(135deg, rgba(43, 179, 163, 0.12), rgba(212, 162, 59, 0.08));
  border: 1px solid var(--tcm-border-soft);
  border-radius: var(--tcm-radius);
}

.syndrome-label {
  font-size: 12px;
  color: var(--tcm-text-dim);
  margin-bottom: 6px;
}

.syndrome-name {
  font-size: 26px;
  font-weight: 700;
  color: var(--tcm-gold);
}

.header-meta {
  display: flex;
  gap: 10px;
  align-items: center;
}

.report-section {
  background: var(--tcm-card);
  border: 1px solid var(--tcm-border-soft);
  border-radius: var(--tcm-radius);
  padding: 18px 20px;
}

.section-title {
  margin: 0 0 14px;
  font-size: 16px;
  color: var(--tcm-primary);
  border-left: 3px solid var(--tcm-primary);
  padding-left: 10px;
}

.section-empty {
  color: var(--tcm-text-faint);
  font-size: 13px;
  margin: 0;
}

.section-text {
  margin: 0;
  line-height: 1.8;
  color: var(--tcm-text);
}

.evidence-item {
  padding: 12px 0;
  border-bottom: 1px dashed var(--tcm-border-soft);
}

.evidence-item:last-child {
  border-bottom: none;
}

.evidence-source {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.evidence-weight {
  font-size: 12px;
  color: var(--tcm-text-faint);
}

.evidence-desc {
  margin: 0;
  color: var(--tcm-text-dim);
  font-size: 13px;
  line-height: 1.7;
}

.plain-list {
  margin: 0;
  padding-left: 20px;
  line-height: 2;
  color: var(--tcm-text-dim);
}

.formula-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.formula-name {
  font-weight: 600;
  color: var(--tcm-text);
}

.formula-source {
  font-size: 12px;
  color: var(--tcm-text-faint);
}

.formula-body {
  color: var(--tcm-text-dim);
  line-height: 1.8;
  font-size: 13px;
}

.formula-line {
  margin: 6px 0;
}

.f-label {
  color: var(--tcm-text);
  font-weight: 500;
}

.formula-note {
  margin: 6px 0;
  padding: 8px 10px;
  background: var(--tcm-bg-soft);
  border-radius: 8px;
}

.formula-warning {
  color: var(--tcm-accent);
  font-size: 12px;
  margin: 8px 0 0;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 4px;
}

.section-head .section-title {
  margin-bottom: 0;
}

.graph-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
  margin-top: 12px;
}

.report-disclaimer {
  padding-top: 4px;
}

.action-bar {
  display: flex;
  gap: 12px;
  padding: 12px 20px;
  background: var(--tcm-card);
  border: 1px solid var(--tcm-border-soft);
  border-radius: var(--tcm-radius);
  flex-wrap: wrap;
}

.action-bar .el-button {
  min-width: 120px;
}

.share-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.share-tip {
  margin: 0;
  color: var(--tcm-text-dim);
  font-size: 13px;
  line-height: 1.6;
}

.share-expire {
  margin: 0;
  font-size: 12px;
  color: var(--tcm-text-faint);
}

.share-expire strong {
  color: var(--tcm-primary);
}
</style>