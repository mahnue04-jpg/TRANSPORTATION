"""
Business Tools
==============

Concrete implementations of business-oriented tools.

Tools:
- BusinessPlanTool: Generate startup plans and business checklists
- ProposalTool: Generate client proposals
- InvoiceTool: Generate invoices and payment emails
- MarketingTool: Generate marketing strategies and campaign ideas
- ResearchTool: Orchestrate research workflows
- EmailDraftTool: Draft professional emails
- MeetingNotesTool: Generate meeting notes from discussions
"""

import time
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from app.tool_registry import BaseTool, ToolExecutionResult

logger = logging.getLogger(__name__)


class BusinessPlanTool(BaseTool):
    """Generate structured business plans for startups."""
    
    def __init__(self):
        super().__init__(
            tool_id='business_plan',
            display_name='Business Plan Generator',
            supported_intents=['business', 'startup', 'plan', 'launch', 'company', 'venture']
        )
    
    async def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        """Generate a business plan."""
        try:
            start_time = time.time()
            message = context.get('message', '')
            memory_prefs = context.get('memory_preferences', {})
            
            # Extract business type from message
            business_type = self._extract_business_type(message)
            
            plan_data = {
                'business_type': business_type,
                'sections': {
                    'executive_summary': self._generate_summary(business_type, memory_prefs),
                    'target_market': self._generate_target_market(business_type),
                    'value_proposition': self._generate_value_proposition(business_type),
                    'revenue_model': self._generate_revenue_model(business_type),
                    'operations_outline': self._generate_operations(business_type),
                    'startup_checklist': self._generate_checklist(business_type),
                },
                'generated_at': datetime.utcnow().isoformat(),
                'execution_ms': int((time.time() - start_time) * 1000)
            }
            
            return ToolExecutionResult(
                tool_id=self.tool_id,
                success=True,
                data=plan_data,
                execution_ms=int((time.time() - start_time) * 1000)
            )
        
        except Exception as e:
            self.logger.error(f"Business plan generation failed: {str(e)}")
            return ToolExecutionResult(
                tool_id=self.tool_id,
                success=False,
                error=str(e),
                fallback_used=True,
                data=self.safe_fallback(str(e))
            )
    
    def safe_fallback(self, error_reason: str) -> Dict[str, Any]:
        """Return fallback business plan outline."""
        return {
            'fallback_outline': [
                'Executive Summary',
                'Target Market Analysis',
                'Value Proposition',
                'Revenue Model Options',
                'Operations Outline',
                'Initial Startup Checklist'
            ],
            'note': 'Here is a suggested business plan structure to get you started.'
        }
    
    def _extract_business_type(self, message: str) -> str:
        """Extract business type from message."""
        keywords = {
            'trucking': ['truck', 'logistics', 'freight', 'transport'],
            'salon': ['salon', 'hair', 'beauty', 'spa'],
            'consulting': ['consult', 'advisory', 'services'],
            'ecommerce': ['shop', 'store', 'ecommerce', 'retail'],
            'saas': ['software', 'app', 'platform', 'saas'],
            'service': ['service', 'freelance']
        }
        
        msg_lower = message.lower()
        for biz_type, kws in keywords.items():
            if any(kw in msg_lower for kw in kws):
                return biz_type
        
        return 'general_business'
    
    def _generate_summary(self, business_type: str, prefs: Dict[str, Any]) -> str:
        """Generate executive summary."""
        templates = {
            'trucking': 'A modern trucking and logistics company providing reliable freight transport services.',
            'salon': 'A professional salon offering premium hair, beauty, and wellness services.',
            'consulting': 'A specialized consulting firm delivering strategic advisory services to growing businesses.',
            'ecommerce': 'An online retail platform offering curated products to a targeted market.',
            'general_business': 'A service-oriented business focused on solving customer pain points.'
        }
        return templates.get(business_type, templates['general_business'])
    
    def _generate_target_market(self, business_type: str) -> str:
        """Generate target market analysis."""
        templates = {
            'trucking': 'Regional manufacturers, e-commerce fulfillment centers, and construction companies.',
            'salon': 'Professionals aged 25-55 seeking premium hair and wellness services.',
            'consulting': 'Mid-market companies (50-500 employees) in growth phases.',
            'ecommerce': 'Niche audience segments with specific product interests.',
            'general_business': 'Local businesses and individual consumers seeking your services.'
        }
        return templates.get(business_type, templates['general_business'])
    
    def _generate_value_proposition(self, business_type: str) -> str:
        """Generate value proposition."""
        templates = {
            'trucking': 'Reliable, on-time delivery with transparent pricing and modern fleet management.',
            'salon': 'Premium services delivered by experienced professionals in a welcoming environment.',
            'consulting': 'Data-driven strategies and practical implementation support.',
            'ecommerce': 'Unique products at competitive prices with excellent customer experience.',
            'general_business': 'Quality services tailored to customer needs with responsive support.'
        }
        return templates.get(business_type, templates['general_business'])
    
    def _generate_revenue_model(self, business_type: str) -> str:
        """Generate revenue model options."""
        templates = {
            'trucking': 'Per-mile pricing, monthly contracts, flat-rate shipments, premium service tiers.',
            'salon': 'Service fees, package deals, retail product sales, membership programs.',
            'consulting': 'Hourly billing, project-based fees, retainer relationships, performance bonuses.',
            'ecommerce': 'Product markup (30-50%), bulk discounts, premium membership, affiliate revenue.',
            'general_business': 'Tiered service pricing, monthly subscriptions, project-based fees.'
        }
        return templates.get(business_type, templates['general_business'])
    
    def _generate_operations(self, business_type: str) -> str:
        """Generate operations outline."""
        templates = {
            'trucking': 'Fleet procurement, route optimization, driver hiring, compliance management, customer support.',
            'salon': 'Staff hiring and training, supply chain, booking system, customer retention programs.',
            'consulting': 'Expertise development, client relationship management, project delivery, quality assurance.',
            'ecommerce': 'Supplier management, inventory, logistics, payment processing, customer service.',
            'general_business': 'Core operations, team structure, customer acquisition, service delivery.'
        }
        return templates.get(business_type, templates['general_business'])
    
    def _generate_checklist(self, business_type: str) -> list:
        """Generate startup checklist."""
        base_checklist = [
            'Register business and obtain licenses',
            'Set up business banking and accounting',
            'Create brand identity and website',
            'Develop marketing strategy',
            'Hire initial team members',
            'Launch MVP or pilot program'
        ]
        return base_checklist


class ProposalTool(BaseTool):
    """Generate client proposals."""
    
    def __init__(self):
        super().__init__(
            tool_id='proposal',
            display_name='Proposal Generator',
            supported_intents=['proposal', 'pitch', 'offer', 'bid']
        )
    
    async def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        """Generate a proposal."""
        try:
            start_time = time.time()
            message = context.get('message', '')
            
            # Extract proposal details from message
            client_name = self._extract_client_name(message)
            project_type = self._extract_project_type(message)
            
            proposal_data = {
                'client_name': client_name,
                'project_type': project_type,
                'proposal_sections': {
                    'title': f"Proposal: {project_type} for {client_name}",
                    'executive_summary': self._generate_proposal_summary(project_type),
                    'scope_of_work': self._generate_scope(project_type),
                    'timeline': self._generate_timeline(project_type),
                    'deliverables': self._generate_deliverables(project_type),
                    'pricing': self._generate_pricing(project_type),
                    'terms': self._generate_terms(),
                },
                'generated_at': datetime.utcnow().isoformat(),
                'execution_ms': int((time.time() - start_time) * 1000)
            }
            
            return ToolExecutionResult(
                tool_id=self.tool_id,
                success=True,
                data=proposal_data,
                execution_ms=int((time.time() - start_time) * 1000)
            )
        
        except Exception as e:
            self.logger.error(f"Proposal generation failed: {str(e)}")
            return ToolExecutionResult(
                tool_id=self.tool_id,
                success=False,
                error=str(e),
                fallback_used=True,
                data=self.safe_fallback(str(e))
            )
    
    def safe_fallback(self, error_reason: str) -> Dict[str, Any]:
        """Return fallback proposal template."""
        return {
            'fallback_template': [
                'Executive Summary',
                'Scope of Work',
                'Timeline and Milestones',
                'Deliverables',
                'Pricing and Payment Terms',
                'Terms and Conditions'
            ],
            'note': 'Here is a standard proposal structure. Customize with your specific details.'
        }
    
    def _extract_client_name(self, message: str) -> str:
        """Extract client name from message."""
        if 'for' in message.lower():
            parts = message.lower().split('for')
            if len(parts) > 1:
                return parts[1].strip()
        return 'Your Client'
    
    def _extract_project_type(self, message: str) -> str:
        """Extract project type from message."""
        keywords = {
            'website': ['website', 'web', 'redesign'],
            'marketing': ['marketing', 'campaign'],
            'consulting': ['consulting', 'advisory'],
            'development': ['development', 'build', 'create'],
            'design': ['design', 'branding', 'logo']
        }
        
        msg_lower = message.lower()
        for ptype, kws in keywords.items():
            if any(kw in msg_lower for kw in kws):
                return ptype.title()
        
        return 'Custom Project'
    
    def _generate_proposal_summary(self, project_type: str) -> str:
        """Generate proposal executive summary."""
        templates = {
            'website': 'We propose a comprehensive website redesign to modernize your online presence.',
            'marketing': 'We propose a strategic marketing campaign to increase brand visibility.',
            'consulting': 'We propose targeted consulting to optimize your operations.',
            'development': 'We propose building a custom solution to meet your business needs.',
            'design': 'We propose a branding initiative to strengthen your market position.'
        }
        return templates.get(project_type, f'We propose to deliver a successful {project_type.lower()} project.')
    
    def _generate_scope(self, project_type: str) -> str:
        """Generate scope of work."""
        return f"Complete {project_type} delivery including planning, execution, and testing."
    
    def _generate_timeline(self, project_type: str) -> str:
        """Generate timeline."""
        return "Estimated 6-12 weeks, with weekly check-ins and monthly progress reports."
    
    def _generate_deliverables(self, project_type: str) -> list:
        """Generate deliverables list."""
        base_deliverables = [
            'Project Plan and Schedule',
            'Progress Reports',
            'Final Deliverable(s)',
            'Documentation',
            'Post-Launch Support'
        ]
        return base_deliverables
    
    def _generate_pricing(self, project_type: str) -> Dict[str, Any]:
        """Generate pricing section."""
        return {
            'total_estimate': '[Custom Quote]',
            'payment_terms': '50% upfront, 50% on completion',
            'note': 'Pricing adjusted based on final scope and timeline confirmation.'
        }
    
    def _generate_terms(self) -> str:
        """Generate standard terms."""
        return "Payment due net 30. Scope changes subject to additional fees."


class InvoiceTool(BaseTool):
    """Generate invoices and payment emails."""
    
    def __init__(self):
        super().__init__(
            tool_id='invoice',
            display_name='Invoice Generator',
            supported_intents=['invoice', 'bill', 'payment']
        )
    
    async def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        """Generate an invoice."""
        try:
            start_time = time.time()
            message = context.get('message', '')
            
            invoice_data = {
                'invoice_number': f"INV-{datetime.now().strftime('%Y%m%d%H%M')}",
                'invoice_sections': {
                    'header': {
                        'from': 'Your Company Name',
                        'to': 'Client Name',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'due_date': '(30 days from invoice date)'
                    },
                    'line_items': self._generate_line_items(message),
                    'summary': {
                        'subtotal': '[Amount]',
                        'tax': '[Tax Amount]',
                        'total': '[Total Amount]'
                    },
                    'payment_section': self._generate_payment_section(),
                    'payment_email_template': self._generate_payment_email()
                },
                'generated_at': datetime.utcnow().isoformat(),
                'execution_ms': int((time.time() - start_time) * 1000)
            }
            
            return ToolExecutionResult(
                tool_id=self.tool_id,
                success=True,
                data=invoice_data,
                execution_ms=int((time.time() - start_time) * 1000)
            )
        
        except Exception as e:
            self.logger.error(f"Invoice generation failed: {str(e)}")
            return ToolExecutionResult(
                tool_id=self.tool_id,
                success=False,
                error=str(e),
                fallback_used=True,
                data=self.safe_fallback(str(e))
            )
    
    def safe_fallback(self, error_reason: str) -> Dict[str, Any]:
        """Return fallback invoice template."""
        return {
            'fallback_template': 'Standard invoice template with line items, totals, and payment terms.',
            'note': 'This is a simulation. Real payments cannot be processed.'
        }
    
    def _generate_line_items(self, message: str) -> list:
        """Generate line items for invoice."""
        return [
            {
                'description': 'Professional Services - Consulting',
                'quantity': 1,
                'rate': '[Per-hour or project rate]',
                'amount': '[Calculated]'
            },
            {
                'description': 'Travel/Materials (if applicable)',
                'quantity': 1,
                'rate': '[Amount]',
                'amount': '[Amount]'
            }
        ]
    
    def _generate_payment_section(self) -> Dict[str, Any]:
        """Generate payment instructions."""
        return {
            'payment_methods': [
                'Bank Transfer',
                'Credit Card',
                'PayPal'
            ],
            'note': '⚠️ This is a SIMULATION. No real payments are processed.',
            'due_terms': 'Net 30 (payment due 30 days from invoice date)'
        }
    
    def _generate_payment_email(self) -> str:
        """Generate payment email template."""
        return """
Subject: Invoice [INV-XXXXXXX] - Payment Due

Dear [Client Name],

Please find attached Invoice [INV-XXXXXXX] for services rendered.

Invoice Details:
- Total Amount: $[Amount]
- Due Date: [Date]
- Description: [Services provided]

Please remit payment to: [Payment details]

Thank you for your business!

Best regards,
[Your Name]
[Your Company]
        """.strip()


class MarketingTool(BaseTool):
    """Generate marketing strategies and campaign ideas."""
    
    def __init__(self):
        super().__init__(
            tool_id='marketing',
            display_name='Marketing Strategy Generator',
            supported_intents=['marketing', 'advertise', 'promote', 'campaign', 'social']
        )
    
    async def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        """Generate marketing strategy."""
        try:
            start_time = time.time()
            message = context.get('message', '')
            
            business_type = self._extract_business_type(message)
            
            marketing_data = {
                'business_type': business_type,
                'marketing_strategy': {
                    'positioning': self._generate_positioning(business_type),
                    'target_audience': self._generate_target_audience(business_type),
                    'channels': self._generate_channels(business_type),
                    'campaign_ideas': self._generate_campaigns(business_type),
                    'social_content': self._generate_social_ideas(business_type),
                    'growth_tactics': self._generate_growth_tactics(business_type),
                },
                'generated_at': datetime.utcnow().isoformat(),
                'execution_ms': int((time.time() - start_time) * 1000)
            }
            
            return ToolExecutionResult(
                tool_id=self.tool_id,
                success=True,
                data=marketing_data,
                execution_ms=int((time.time() - start_time) * 1000)
            )
        
        except Exception as e:
            self.logger.error(f"Marketing generation failed: {str(e)}")
            return ToolExecutionResult(
                tool_id=self.tool_id,
                success=False,
                error=str(e),
                fallback_used=True,
                data=self.safe_fallback(str(e))
            )
    
    def safe_fallback(self, error_reason: str) -> Dict[str, Any]:
        """Return fallback marketing outline."""
        return {
            'fallback_outline': [
                'Market Positioning',
                'Target Audience Definition',
                'Marketing Channels',
                'Campaign Ideas',
                'Social Media Strategy',
                'Growth Tactics'
            ],
            'note': 'Here is a marketing strategy template to customize for your business.'
        }
    
    def _extract_business_type(self, message: str) -> str:
        """Extract business type."""
        keywords = {
            'salon': ['salon', 'hair', 'beauty'],
            'consulting': ['consulting', 'services'],
            'ecommerce': ['shop', 'store', 'products'],
            'general': ['business', 'service']
        }
        msg_lower = message.lower()
        for btype, kws in keywords.items():
            if any(kw in msg_lower for kw in kws):
                return btype
        return 'general'
    
    def _generate_positioning(self, business_type: str) -> str:
        """Generate market positioning."""
        templates = {
            'salon': 'Premium, personalized beauty services for professionals.',
            'consulting': 'Expert advisory for growing companies.',
            'ecommerce': 'Curated products at competitive prices.',
            'general': 'Quality services tailored to customer needs.'
        }
        return templates.get(business_type, templates['general'])
    
    def _generate_target_audience(self, business_type: str) -> str:
        """Generate target audience."""
        templates = {
            'salon': 'Professionals aged 25-55 seeking premium services.',
            'consulting': 'Mid-market companies in growth phases.',
            'ecommerce': 'Online shoppers seeking [product category].',
            'general': 'Customers seeking quality [service type].'
        }
        return templates.get(business_type, templates['general'])
    
    def _generate_channels(self, business_type: str) -> list:
        """Generate marketing channels."""
        base_channels = [
            'Social Media (Instagram, LinkedIn, Facebook)',
            'Email Marketing',
            'Content Marketing (Blog, Videos)',
            'Local SEO',
            'Referral Programs',
            'Paid Advertising'
        ]
        return base_channels
    
    def _generate_campaigns(self, business_type: str) -> list:
        """Generate campaign ideas."""
        templates = {
            'salon': [
                'Launch special loyalty program',
                'Before/after transformation series',
                'Seasonal promotion campaigns'
            ],
            'consulting': [
                'Industry insight webinars',
                'Case study series',
                'Expert commentary on trends'
            ],
            'ecommerce': [
                'Seasonal product launches',
                'Flash sale campaigns',
                'User-generated content campaigns'
            ],
            'general': [
                'Customer success stories',
                'Seasonal promotions',
                'Referral incentive campaigns'
            ]
        }
        return templates.get(business_type, templates['general'])
    
    def _generate_social_ideas(self, business_type: str) -> Dict[str, list]:
        """Generate social media content ideas."""
        return {
            'instagram': [
                'Behind-the-scenes content',
                'Customer testimonials',
                'Tips and tricks',
                'Team spotlight'
            ],
            'linkedin': [
                'Industry insights',
                'Company updates',
                'Thought leadership articles',
                'Recruitment posts'
            ],
            'facebook': [
                'Community engagement',
                'Event announcements',
                'Customer reviews',
                'Educational content'
            ]
        }
    
    def _generate_growth_tactics(self, business_type: str) -> list:
        """Generate growth tactics."""
        return [
            'Build email list for direct communication',
            'Implement referral rewards program',
            'Create strategic partnerships',
            'Optimize for local search visibility',
            'Develop thought leadership content',
            'Engage actively in community'
        ]


class ResearchCollectorTool(BaseTool):
    """Collects structured research scaffolding and summary plan."""

    def __init__(self):
        super().__init__(
            tool_id='research_collector',
            display_name='Research Collector',
            supported_intents=['research', 'summarize', 'analyze', 'investigate']
        )

    async def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        message = context.get('message', '')
        card = {
            'title': 'Research Brief',
            'category': 'research',
            'preview': f"Research plan prepared for: {message[:90]}",
            'timestamp': datetime.utcnow().isoformat(),
            'actions': ['Open in Browser', 'Refine Query']
        }
        return ToolExecutionResult(
            tool_id=self.tool_id,
            success=True,
            data={
                'topic': message,
                'approach': [
                    'Define scope and success criteria',
                    'Collect high-confidence sources',
                    'Extract key findings and risks',
                    'Summarize into action-ready bullets',
                ],
                'card': card,
            },
        )

    def safe_fallback(self, error_reason: str) -> Dict[str, Any]:
        return {
            'note': 'Research helper unavailable right now. I can still provide a concise manual research outline.'
        }


class EmailDraftBuilderTool(BaseTool):
    """Creates structured email draft metadata."""

    def __init__(self):
        super().__init__(
            tool_id='email_draft_builder',
            display_name='Email Draft Builder',
            supported_intents=['email', 'draft email', 'compose email', 'prepare email']
        )

    async def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        message = context.get('message', '')
        card = {
            'title': 'Email Draft',
            'category': 'email',
            'preview': f"Draft prepared for: {message[:90]}",
            'timestamp': datetime.utcnow().isoformat(),
            'actions': ['Copy Draft', 'Edit Tone']
        }
        return ToolExecutionResult(
            tool_id=self.tool_id,
            success=True,
            data={
                'email_outline': {
                    'subject': '[Subject line]',
                    'opening': 'Hi [Name],',
                    'body': 'Main message and requested action.',
                    'closing': 'Best regards,\n[Your Name]'
                },
                'card': card,
            },
        )

    def safe_fallback(self, error_reason: str) -> Dict[str, Any]:
        return {'note': 'Email draft builder is unavailable. Returning a simple email structure instead.'}


class BrowserOpenTool(BaseTool):
    """Extracts URL actions for embedded browser launching."""

    def __init__(self):
        super().__init__(
            tool_id='browser_open',
            display_name='Embedded Browser Opener',
            supported_intents=['browser_open', 'open', 'visit']
        )

    async def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        import re

        message = context.get('message', '')
        urls = re.findall(r'https?://\S+|www\.\S+', message)
        normalized_urls = [u if u.startswith('http') else f'https://{u}' for u in urls]
        card = {
            'title': 'Open in Browser',
            'category': 'browser',
            'preview': normalized_urls[0] if normalized_urls else 'No URL detected',
            'timestamp': datetime.utcnow().isoformat(),
            'actions': ['Open in Browser'] if normalized_urls else []
        }
        return ToolExecutionResult(
            tool_id=self.tool_id,
            success=bool(normalized_urls),
            data={
                'urls': normalized_urls,
                'browser_actions': [{'label': 'Open in Browser', 'url': u} for u in normalized_urls],
                'card': card,
            },
            error=None if normalized_urls else 'No URL found in message',
            fallback_used=not bool(normalized_urls),
        )

    def safe_fallback(self, error_reason: str) -> Dict[str, Any]:
        return {'note': 'I could not open the URL automatically. You can still open it manually in the embedded browser.'}


class MemoryLookupTool(BaseTool):
    """Memory lookup helper metadata tool."""

    def __init__(self):
        super().__init__(
            tool_id='memory_lookup',
            display_name='Memory Lookup',
            supported_intents=['memory_lookup', 'remember', 'what do you know about me']
        )

    async def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        card = {
            'title': 'Memory Lookup',
            'category': 'memory',
            'preview': 'Memory-aware response path confirmed',
            'timestamp': datetime.utcnow().isoformat(),
            'actions': ['Review Memory Settings']
        }
        return ToolExecutionResult(
            tool_id=self.tool_id,
            success=True,
            data={'memory_lookup': True, 'card': card},
        )

    def safe_fallback(self, error_reason: str) -> Dict[str, Any]:
        return {'note': 'Memory lookup helper unavailable. Core memory response remains active.'}


class WorkflowRunnerTool(BaseTool):
    """Composes multi-step business workflows."""

    def __init__(self):
        super().__init__(
            tool_id='workflow_runner',
            display_name='Workflow Runner',
            supported_intents=['workflow', 'launch', 'help me launch', 'orchestrate']
        )

    async def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        message = context.get('message', '')
        steps = [
            'Generate startup checklist',
            'Generate pricing ideas',
            'Generate marketing suggestions',
            'Generate business plan summary',
            'Recommend next steps',
        ]
        card = {
            'title': 'Workflow Plan',
            'category': 'workflow',
            'preview': f"5-step assistant workflow prepared for: {message[:75]}",
            'timestamp': datetime.utcnow().isoformat(),
            'actions': ['Run Workflow', 'Customize Steps']
        }
        return ToolExecutionResult(
            tool_id=self.tool_id,
            success=True,
            data={'workflow_steps': steps, 'card': card},
        )

    def safe_fallback(self, error_reason: str) -> Dict[str, Any]:
        return {'note': 'Workflow runner unavailable. I can still provide a manual step-by-step plan.'}


# Register tools on import
def register_default_tools(registry):
    """Register all default business tools."""
    registry.register(BusinessPlanTool())
    registry.register(ProposalTool())
    registry.register(InvoiceTool())
    registry.register(MarketingTool())
    registry.register(ResearchCollectorTool())
    registry.register(EmailDraftBuilderTool())
    registry.register(BrowserOpenTool())
    registry.register(WorkflowRunnerTool())
    registry.register(MemoryLookupTool())
    logger.info("Business tools registered")
