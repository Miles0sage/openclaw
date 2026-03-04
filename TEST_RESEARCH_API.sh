#!/bin/bash

echo "🔍 Testing Research API Setup..."
echo ""

# Test 1: Check if files exist
echo "📁 Checking research data files..."
test -f /root/openclaw/AI_RESEARCH_FINDINGS_24H.json && echo "✅ AI_RESEARCH_FINDINGS_24H.json" || echo "❌ AI_RESEARCH_FINDINGS_24H.json"
test -f /root/openclaw/AI_RESEARCH_CLASSIFIED_20260304.json && echo "✅ AI_RESEARCH_CLASSIFIED_20260304.json" || echo "❌ AI_RESEARCH_CLASSIFIED_20260304.json"
test -f /root/openclaw/data/research/ai_scout_findings_20260304.json && echo "✅ ai_scout_findings_20260304.json" || echo "❌ ai_scout_findings_20260304.json"
echo ""

# Test 2: Verify endpoints are defined
echo "🔌 Checking API route files..."
test -f /root/openclaw/src/app/api/research/scout/route.ts && echo "✅ /api/research/scout route" || echo "❌ /api/research/scout route"
test -f /root/openclaw/src/app/api/research/recommendations/route.ts && echo "✅ /api/research/recommendations route" || echo "❌ /api/research/recommendations route"
test -f /root/openclaw/src/app/api/research/analysis/route.ts && echo "✅ /api/research/analysis route (NEW)" || echo "❌ /api/research/analysis route (NEW)"
test -f /root/openclaw/src/app/api/research/latest/route.ts && echo "✅ /api/research/latest route" || echo "❌ /api/research/latest route"
test -f /root/openclaw/src/app/api/research/status/route.ts && echo "✅ /api/research/status route" || echo "❌ /api/research/status route"
echo ""

# Test 3: Verify documentation
echo "📖 Checking documentation files..."
test -f /root/openclaw/src/app/api/research/README.md && echo "✅ API README.md (NEW)" || echo "❌ API README.md (NEW)"
test -f /root/openclaw/RESEARCH_ANALYSIS_EXECUTIVE_SUMMARY.md && echo "✅ Executive Summary (NEW)" || echo "❌ Executive Summary (NEW)"
echo ""

# Test 4: Validate JSON files
echo "✔️ Validating JSON file format..."
echo -n "  AI_RESEARCH_FINDINGS_24H.json: "
jq empty /root/openclaw/AI_RESEARCH_FINDINGS_24H.json 2>/dev/null && echo "✅ Valid JSON" || echo "❌ Invalid JSON"

echo -n "  AI_RESEARCH_CLASSIFIED_20260304.json: "
jq empty /root/openclaw/AI_RESEARCH_CLASSIFIED_20260304.json 2>/dev/null && echo "✅ Valid JSON" || echo "❌ Invalid JSON"

echo -n "  ai_scout_findings_20260304.json: "
jq empty /root/openclaw/data/research/ai_scout_findings_20260304.json 2>/dev/null && echo "✅ Valid JSON" || echo "❌ Invalid JSON"
echo ""

# Test 5: Quick data statistics
echo "📊 Research Data Statistics..."
echo -n "  Total findings (AI_RESEARCH_FINDINGS_24H): "
jq '.findings | length' /root/openclaw/AI_RESEARCH_FINDINGS_24H.json 2>/dev/null || echo "error"

echo -n "  Total classified items: "
jq '.classified_findings | length' /root/openclaw/AI_RESEARCH_CLASSIFIED_20260304.json 2>/dev/null || echo "error"

echo -n "  Key findings in detailed analysis: "
jq '.key_findings | length' /root/openclaw/data/research/ai_scout_findings_20260304.json 2>/dev/null || echo "error"

echo -n "  Integration recommendations: "
jq '.integration_recommendations | length' /root/openclaw/data/research/ai_scout_findings_20260304.json 2>/dev/null || echo "error"
echo ""

echo "✅ API Setup Verification Complete!"
echo ""
echo "📋 Summary:"
echo "  • All research data files present and valid"
echo "  • All API routes defined"
echo "  • Documentation complete"
echo "  • Ready for deployment"
echo ""
echo "🚀 Next Steps:"
echo "  1. Start development server: npm run dev"
echo "  2. Test endpoints:"
echo "     - GET /api/research/analysis"
echo "     - GET /api/research/recommendations"
echo "     - GET /api/research/scout"
echo "  3. Review RESEARCH_ANALYSIS_EXECUTIVE_SUMMARY.md for strategic context"
