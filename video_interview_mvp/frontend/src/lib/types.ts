export type VacancyStatus = 'draft' | 'active' | 'closed'
export type Stage = 'applied' | 'invited' | 'interviewed' | 'advanced' | 'rejected'

export interface VacancyCardData {
  id: number
  title: string
  grade: string | null
  status: VacancyStatus
  detected_tags: string[]
  created_at: string | null
  closed_at: string | null
  questions_count: number
  approved_questions_count: number
  candidates_total: number
  stage_counts: Record<Stage, number>
}

export interface CandidateCardData {
  id: number
  name: string
  stage: Stage
  waiting_on: 'recruiter' | 'candidate' | 'manager' | null
  days_in_stage: number | null
  workflow_state: string
  lifecycle_status: string
  created_at: string | null
  invited_at: string | null
  completed_at: string | null
  interview_url: string
  overall_score: number | null
  recommendation: string | null
  has_report: boolean
  email: string | null
  telegram_username: string | null
  telegram_linked: boolean
  resume_filename: string | null
  match_score: number | null
  match_summary: string | null
  question_count: number
}

export interface BoardColumn {
  key: Stage
  title: string
  hint: string
  candidates: CandidateCardData[]
}

export interface Requirement {
  skill: string
  weight: number
  evidence: string
}

export interface BoardStats {
  total: number
  invited: number
  completed: number
  decided: number
  advanced: number
  completion_rate: number | null
  pass_rate: number | null
  avg_score: number | null
  median_days_to_complete: number | null
  awaiting_decision: number
}

export interface VacancyDetail {
  id: number
  title: string
  grade: string | null
  status: VacancyStatus
  detected_tags: string[]
  vacancy_text: string
  created_at: string | null
  closed_at: string | null
  questions_count: number
  approved_questions_count: number
  summary: string
  must_have: Requirement[]
  nice_to_have: Requirement[]
  stop_factors: string[]
  responsibilities: string[]
}

export interface BoardResponse {
  vacancy: VacancyDetail
  stats: BoardStats
  columns: BoardColumn[]
}

export interface SkillEntry {
  skill: string
  questions: number
  competencies: string[]
}

export interface CurrentUser {
  username: string
  role: 'hr' | 'hiring_manager'
  full_name: string | null
}

export interface CandidateRow extends CandidateCardData {
  vacancy_id: number
  vacancy_title: string
  vacancy_grade: string | null
}

export interface CandidatesResponse {
  candidates: CandidateRow[]
  vacancies: Array<{ id: number; title: string }>
  counts: {
    total: number
    waiting_recruiter: number
    waiting_manager: number
    waiting_candidate: number
  }
}

export interface BankQuestionRow {
  bank_id: string | null
  database_id: number | null
  question: string
  competency: string
  tags: string[]
  must_have: string[]
  nice_to_have: string[]
  red_flags: string[]
  reference_answer: string
  possible_extra_questions: string[]
  usage_count: number
}

export interface MediaInfo {
  exists: boolean
  size_bytes: number
  duration_ms: number
  playable: boolean
}

export interface AnswerAnalysis {
  score_0_10?: number
  covered_must_have: string[]
  missing_must_have: string[]
  covered_nice_to_have: string[]
  red_flags_found: string[]
  evidence_quotes: string[]
  summary: string
  confidence_0_1?: number
  strengths: string[]
  weaknesses: string[]
  detected_red_flags: string[]
}

export interface ReportAnswer {
  id: number
  question: string
  transcript: string
  score: number | null
  is_follow_up: boolean
  root_question_id: number | null
  follow_up_index: number | null
  probe_reason: string
  probe_focus: string
  probe_source: string
  audio_path: string | null
  video_path: string | null
  audio_media: MediaInfo | null
  video_media: MediaInfo | null
  start_ms: number
  end_ms: number
  analysis: AnswerAnalysis | null
}

export interface CoverageItem {
  topic?: string
  requirement?: string
  skill?: string
  status?: string
  evidence?: string
  evidence_quotes?: string[]
  question_ids?: string[]
}

export interface ReportResponse {
  id: number
  session_id: number
  candidate_name: string
  vacancy_title: string
  overall_score: number | null
  recommendation: string
  summary: string
  score_confidence: number | null
  strengths: unknown[]
  weaknesses: unknown[]
  risk_factors: unknown[]
  areas_to_check: unknown[]
  vacancy_coverage: { must_have: CoverageItem[]; nice_to_have: CoverageItem[] }
  final_evaluation: {
    competencies: Array<{ name?: string; score_0_10?: number; summary?: string; evidence?: string[] }>
    uncovered_vacancy_topics: string[]
    strengths: Array<{ text?: string; evidence?: string } | string>
    issues: Array<{ text?: string; evidence?: string } | string>
  } | null
  answers: ReportAnswer[]
  full_video_path: string | null
  full_video_media: MediaInfo | null
  generated_at: string
  workflow_state: string
  viewer_role: 'hr' | 'hiring_manager'
  hr_review: { decision: string; comment: string } | null
  manager_review: { decision: string; comment: string } | null
}
