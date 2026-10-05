"""October public-site refresh: services first, with verified Nova entry points."""
from html import escape

APP = 'https://amicor-health-isf-py.onrender.com'
LOGIN = APP + '/nova?signin=1'
AGENT = APP + '/nova/anonymous-agent'
CREATIVE = APP + '/nova/creative'
SIGNUP = APP + '/nova/signup'


def apply(add, pages, status_table):
    def replace(route, title, description, body):
        filename = 'index.html' if route == '/' else route.strip('/') + '/index.html'
        pages[:] = [p for p in pages if p['filename'] != filename]
        add(route, filename, title, description, route, route.count('/') - 1, body)

    def hero(kicker, title, text, actions=''):
        return f'<section class="hero"><div class="wrap"><p class="kicker">{kicker}</p><h1>{title}</h1><p class="lede">{text}</p><div class="hero-actions">{actions}</div></div></section>'

    def button(url, label, primary=True):
        return f'<a class="btn {"btn-primary" if primary else "btn-ghost"}" href="{escape(url, quote=True)}">{label}</a>'

    def section(title, body):
        return f'<section class="section"><div class="wrap"><h2>{title}</h2>{body}</div></section>'

    def card(title, text, url, label='Learn more'):
        return f'<article class="card"><h3>{title}</h3><p>{text}</p><a class="card-link" href="{escape(url, quote=True)}">{label}</a></article>'

    service_cards = '<div class="grid grid-3">' + ''.join([
        card('Research &amp; reports', 'Public-source research, cited findings, document preparation, and concise reports you can review.', '/business-services/'),
        card('Data &amp; administrative support', 'Spreadsheet cleanup, task registers, document organization, and customer-support drafts.', '/business-services/'),
        card('CRM &amp; workflow assessment', 'Map your current process, identify gaps, and build a prioritized improvement plan.', '/business-services/'),
    ]) + '</div>'
    product_cards = '<div class="grid grid-3">' + ''.join([
        card('Ask Nova', 'Research questions, organize ideas, and prepare drafts in your Nova account.', '/ask-nova/'),
        card('Nova Operations Agent', 'Submit a digital business task, explore the interactive demo, or start a seven-day trial.', '/nova-operations/'),
        card('Nova Creative Studio', 'Plan scripts, storyboards, captions, and branded assets. Media generation depends on enabled providers and credits.', '/nova-create/'),
    ]) + '</div>'
    plans = '<div class="price-grid">' + ''.join([
        card('Explore &amp; scope', '<strong>$0</strong>Explore the public demo and request a scope check. The Nova app also offers a seven-day account trial with no card required.', AGENT, 'Explore the demo'),
        card('Starter Task', '<strong>$49 one-time</strong>A supported starter task, with scope reviewed before work begins.', AGENT, 'Request a starter task'),
        card('Launch Operations', '<strong>$99/month</strong>Recurring supported digital operations. Confirm the scope and plan details in the Nova app.', AGENT, 'View plan'),
        card('Business Operations', '<strong>$299/month</strong>Business operations support within an agreed scope. Complex projects are quoted separately.', AGENT, 'View plan'),
    ]) + '</div><p class="notice">These are the starting options listed in the Nova app as of October 5, 2026. Review current terms and scope there before purchase. This corporate website does not collect payment. Media-provider credits and complex projects are not represented as included.</p>'

    replace('/', 'AMICOR — Business Services and Nova AI Tools',
        'AI-assisted business research, administrative support, CRM and workflow assessment, and Nova software from Minnesota-based AMICOR.',
        hero('AMICOR · Minnesota, USA', 'Less busywork.<br>More room to build.',
             'Research, reports, data cleanup, and workflow support—with AI-assisted preparation and human review.',
             button('/business-services/', 'Explore Business Services') + button(AGENT, 'Try Nova', False))
        + section('Bring us the work that slows you down', service_cards)
        + section('Meet Nova', product_cards + '<p>Existing customer? <a href="/signin/">Sign in to your Nova account</a>. New customer? <a href="' + SIGNUP + '">Start a seven-day trial</a>.</p>')
        + section('See how a task becomes a deliverable', '<div class="grid grid-3"><article class="card"><h3>1. Define the result</h3><p>Share your goal, inputs, deadline, and acceptance criteria.</p></article><article class="card"><h3>2. Prepare &amp; review</h3><p>AMICOR checks the scope. Nova assists with supported work, and a person reviews the output.</p></article><article class="card"><h3>3. Deliver the work</h3><p>Receive the agreed materials with sources, assumptions, and next steps where relevant.</p></article></div>')
        + section('Evaluate before you commit', button(AGENT, 'Run the Interactive Demo') + ' ' + button('/samples/', 'View Sample Deliverables', False) + '<p>The app demo illustrates a lead workflow. It does not contact customers or change a live CRM. Samples are fictional examples, not client case studies.</p>')
        + section('Future AMICOR initiatives', '<p>Transportation, local delivery, Lifesaver, and connected hardware remain on separate development timelines.</p><div class="grid grid-3">' + card('Health &amp; Deliver', 'Transportation and delivery technology in development; public ride and delivery orders are not offered here.', '/health/') + card('Lifesaver AI Care Cloud', 'A connected-care technology initiative in development.', '/lifesaver/') + card('Home Hub &amp; Car Hub', 'Future hardware concepts; not for sale.', '/home-hub/') + '</div><p><a href="/products/">View the full product catalog and status</a></p>'))

    replace('/business-services/', 'AMICOR Business Services — Research, Data and CRM Support',
        'Request scoped research, administrative support, data cleanup, documentation, and CRM workflow assessment from AMICOR.',
        hero('Business Services', 'Turn a backlog into useful work.', 'Bring a defined project or recurring digital task. We agree on the deliverables and review process before work starts.', button('/early-access/?product=Business%20Services&intent=quote', 'Request a Project Quote') + button('/samples/', 'See Samples', False))
        + section('What we can prepare', service_cards + '<div class="grid grid-3">' + card('Documentation &amp; SOPs', 'Process guides, checklists, report formatting, and structured task or deadline tracking.', '/samples/') + card('Proposal &amp; RFP support', 'Organize requirements, prepare a response outline, and track missing inputs for owner review.', '/samples/') + card('Customer-support operations', 'Triage categories, response drafts, follow-up registers, and escalation workflows.', '/nova-operations/') + '</div>')
        + section('CRM assessment &amp; strategic planning', '<p>A scoped assessment can include stakeholder questions, a current-state workflow map, data-quality findings, options for improvement, a prioritized roadmap, and an executive readout. Software implementation and integrations are scoped separately.</p>')
        + section('How we scope your project', '<p>Tell us the outcome, source materials, approximate volume, deadline, and required output format. We confirm feasibility, access, price, and acceptance criteria before accepting the work.</p><p>AI use is disclosed. Work uses public or client-approved materials in an agreed environment. Licensed advice, clinical services, and regulated filings require appropriately qualified professionals.</p>')
        + section('For procurement and partner teams', button('/company-profile/', 'View Company Profile') + ' ' + '<a class="btn btn-ghost" href="/company-profile/index.html" download="AMICOR-Company-Profile.html">Download Profile HTML</a>'))

    replace('/ask-nova/', 'Ask Nova — AMICOR AI Assistant', 'Explore Ask Nova for research, ideas and drafts in your AMICOR Nova account.',
        hero('Nova software', 'Ask Nova', 'Get help researching questions, organizing information, and preparing drafts you can review.', button(LOGIN, 'Open Ask Nova') + button(SIGNUP, 'Create a Nova Account', False))
        + section('Start with a practical question', '<div class="grid grid-3"><article class="card"><h3>Research</h3><p>Ask for a comparison or a source-backed research outline. Check the cited sources before relying on the answer.</p></article><article class="card"><h3>Draft</h3><p>Prepare email, report, checklist, and planning drafts from information you provide.</p></article><article class="card"><h3>Organize</h3><p>Break a project into tasks, questions, and next steps.</p></article></div><p>Account access and available tools depend on your plan. Sign-in is currently required for Mrs. Nova Brain.</p>'))

    operations = hero('Nova software', 'Nova Operations Agent', 'Supported digital operations with scope checks and human review. Explore the demo or submit a business task.', button(AGENT, 'Open Operations Agent') + button(SIGNUP, 'Start a Seven-Day Trial', False))
    operations += section('Supported work', service_cards + '<p>Administrative operations, research, spreadsheets, documentation, customer-support preparation, workflow support, and proposal organization are listed in the app. Supported work stays within the approved engagement.</p>')
    operations += section('Starting options', plans)
    operations += section('Try the lead-workflow demo', '<p>Enter a sample inquiry in the public app and see how Nova organizes work for owner review. The demo is a sandbox and does not send email, update a CRM, or charge money.</p>' + button(AGENT, 'Run the Interactive Demo'))
    replace('/nova-operations/', 'Nova Operations Agent — AMICOR Business Support', 'Explore Nova Operations Agent, its public demo, trial and starting plans.', operations)
    replace('/technologies/autonomous-operations-agent/', 'Nova Operations Agent — AMICOR', 'Nova Operations Agent provides supported digital business work with human review.', operations)
    replace('/pricing/', 'AMICOR Nova Pricing and Project Quotes', 'Nova starting options: free exploration, $49 starter task, $99/month and $299/month. Complex projects are quoted separately.',
        hero('Pricing', 'Start small. Scope the work clearly.', 'Explore Nova before choosing a task or recurring support plan.', button(SIGNUP, 'Start a Seven-Day Trial') + button('/early-access/?product=Business%20Services&intent=quote', 'Request a Project Quote', False)) + section('Nova Operations Agent', plans) + section('Larger projects', '<p>Research projects, CRM assessments, custom workflow design, and other complex engagements receive a separate quote based on scope and deliverables.</p>'))
    replace('/signin/', 'Sign In to AMICOR Nova', 'Use your existing Nova account or create an account for the seven-day trial.',
        hero('Your Nova account', 'Welcome back.', 'Continue to the Nova app to sign in with your existing account.', button(LOGIN, 'Sign In to Nova') + button(SIGNUP, 'Create an Account', False)) + section('One account, your Nova workspace', '<p>Use your account for Ask Nova and the Operations Agent. Product and module access depend on your plan. Creative Studio requires sign-in and enabled capabilities.</p>'))
    replace('/nova-create/', 'Nova Creative Studio — Scripts, Storyboards and Branded Assets', 'Plan scripts, captions, storyboards and branded assets in Nova Creative Studio.',
        hero('Nova software · Supervised release', 'Creative Studio', 'Develop ideas into scripts, captions, storyboards, and branded creative assets.', button(CREATIVE, 'Open Creative Studio') + button('/early-access/?product=Nova%20Creative%20Studio&intent=demo', 'Request a Demo', False)) + section('Plan, create, review', '<div class="grid grid-3"><article class="card"><h3>Content planning</h3><p>Build a brief, script, caption, and storyboard around your audience and goal.</p></article><article class="card"><h3>Media generation</h3><p>Image, video, and voice tools depend on configured providers, account permissions, and credits.</p></article><article class="card"><h3>Review &amp; export</h3><p>Review available outputs before publishing. Video rendering is still being improved; generation and exports may fail.</p></article></div><p>Creative Studio is not advertised as an unlimited media plan. Provider costs, watermarks, licensing, and production readiness require review.</p>'))

    catalog = hero('Products', 'Nova software. Future AMICOR initiatives.', 'Explore the software paths and see the status of the wider ecosystem.') + section('Nova', product_cards) + section('Product status', status_table)
    replace('/products/', 'AMICOR Products — Nova and Future Initiatives', 'Explore Ask Nova, Operations Agent, Creative Studio and AMICOR product status.', catalog)
    replace('/technologies/', 'AMICOR Technologies — Nova Software', 'Ask Nova, Operations Agent and Creative Studio software from AMICOR.', hero('AMICOR Technologies', 'Tools for everyday business work.', 'Nova brings questions, supported digital tasks, and creative preparation into an AI-assisted workspace.') + section('Explore Nova', product_cards))
    replace('/about/', 'About AMICOR — Minnesota Business and Technology', 'Learn about AMICOR, founder Saye Monibah, and our approach to supervised business support.',
        hero('About AMICOR', 'Built around practical work.', 'AMICOR is a Minnesota business developing Nova software and offering scoped, AI-assisted digital operations support.') + section('Founder', '<p>Saye Monibah founded AMICOR to help businesses organize work and reduce administrative friction. Nova supports preparation; people define the scope, review the work, and control external handoffs.</p>') + section('Our approach', '<div class="grid grid-3"><article class="card"><h3>Clear scope</h3><p>Agree on the deliverable, inputs, deadline, and acceptance criteria.</p></article><article class="card"><h3>Human review</h3><p>Review AI-assisted output, sources, assumptions, and decisions before delivery.</p></article><article class="card"><h3>Truthful availability</h3><p>Keep available services, supervised software, and future initiatives clearly described.</p></article></div>') + section('Company information', '<p>Public brand: AMICOR. Location: Minnesota, United States. Contact: <a href="mailto:info@getamicor.com">info@getamicor.com</a>.</p><p>The existing website identifies the business as AMICOR HEALTH ISF LLC. Procurement documents use the legal entity details verified for the engagement.</p>' + button('/company-profile/', 'View Company Profile')))
    replace('/contact/', 'Contact AMICOR — Projects, Demos and Partnerships', 'Contact AMICOR about business services, Nova demos or partnerships.',
        hero('Contact', 'What would you like help with?', 'Choose the inquiry that fits your goal, or email info@getamicor.com.') + section('Start a conversation', '<div class="grid grid-3">' + card('A project or recurring work', 'Tell us the outcome, deadline, and approximate volume.', '/early-access/?product=Business%20Services&intent=quote', 'Request a Project Quote') + card('A Nova demonstration', 'Ask about supported workflows and account access.', '/early-access/?product=Nova%20Operations%20Agent&intent=demo', 'Request a Demo') + card('A partnership', 'Discuss procurement, collaboration, or product review.', '/early-access/?product=Partnership', 'Contact Partnerships') + '</div><p>Email: <a href="mailto:info@getamicor.com">info@getamicor.com</a>. Please keep initial inquiries free of medical records, account credentials, and other sensitive information.</p>'))

    sample_body = hero('Sample deliverables', 'See the shape of the work.', 'These fictional examples show possible output formats. They are not completed client projects or testimonials.')
    sample_body += section('Research register', '<div class="table-wrap"><table><thead><tr><th>Question</th><th>Source to review</th><th>Finding</th><th>Next step</th></tr></thead><tbody><tr><td>Does an opportunity allow remote delivery?</td><td>Client-provided tender, section 4</td><td>Example: delivery model needs clarification</td><td>Ask the buyer before preparing the response</td></tr><tr><td>Which documents are required?</td><td>Client-provided checklist</td><td>Example: two supporting documents are missing</td><td>Assign an owner and due date</td></tr></tbody></table></div>')
    sample_body += section('CRM assessment outline', '<ol><li>Stakeholder needs and current workflow</li><li>Data sources, duplicates, and handoff gaps</li><li>Options, assumptions, and implementation dependencies</li><li>Prioritized recommendations and acceptance criteria</li><li>Executive summary and next-step roadmap</li></ol>')
    sample_body += section('Task &amp; follow-up register', '<div class="table-wrap"><table><thead><tr><th>Task</th><th>Owner</th><th>Status</th><th>Review needed</th></tr></thead><tbody><tr><td>Clean duplicate inquiry rows</td><td>Project coordinator</td><td>Draft prepared</td><td>Confirm merge rules</td></tr><tr><td>Prepare customer response</td><td>Business owner</td><td>Awaiting approval</td><td>Approve wording before sending</td></tr></tbody></table></div>')
    sample_body += section('Explore a working demonstration', '<p>The public Operations Agent demo lets you enter a sample lead and inspect the structured result.</p>' + button(AGENT, 'Open the Demo'))
    replace('/samples/', 'AMICOR Sample Deliverables — Research, CRM and Task Registers', 'Fictional examples of AMICOR research, CRM assessment and operations deliverables.', sample_body)
    profile = hero('Company profile · October 2026', 'AMICOR', 'Minnesota-based business services and Nova software. Founder: Saye Monibah.')
    profile += section('Core capabilities', '<ul><li>Public-source research and cited reports</li><li>Spreadsheet cleanup and data organization</li><li>Administrative support and document preparation</li><li>CRM and workflow assessment</li><li>SOPs, task registers, and proposal organization</li><li>Creative briefs, scripts, captions, and storyboards</li></ul>')
    profile += section('Delivery approach', '<p>Remote, scoped engagements using public or client-approved inputs. AI-assisted preparation with human review. Deliverables, access, deadlines, and acceptance criteria are agreed before work begins.</p>')
    profile += section('Company &amp; contact', '<p>Public brand: AMICOR. Founder: Saye Monibah. Location: Minnesota, USA.</p><p>Website: <a href="https://getamicor.com/">getamicor.com</a><br>Email: <a href="mailto:info@getamicor.com">info@getamicor.com</a></p><p>Legal entity identifiers, registration status, insurance, references, and contract-specific qualifications are supplied only after verification. This profile makes no claim of federal past performance, certifications, awarded contracts, or guaranteed outcomes.</p><p><button class="btn btn-primary" type="button" data-print>Print / Save as PDF</button> <a class="btn btn-ghost" href="/company-profile/index.html" download="AMICOR-Company-Profile.html">Download HTML Profile</a></p>')
    replace('/company-profile/', 'AMICOR Company Profile — Business Services and Nova', 'AMICOR company capabilities, delivery approach and business contact details.', profile)

    # Keep the existing validated form and storage path, but make inquiry options explicit.
    for p in pages:
        if p['filename'] == 'early-access/index.html':
            p['html'] = p['html'].replace('Tell us what you want to explore.', 'Tell us what you need.').replace('Partners / Early Access', 'Projects / Demos / Partnerships').replace('Interested product', 'What is your inquiry about?').replace('<option>Autonomous Operations Agent</option>', '<option>Business Services</option><option>Ask Nova</option><option>Nova Operations Agent</option><option>Nova Creative Studio</option><option>Autonomous Operations Agent</option>').replace('This form is for customers, partners, insurers, reviewers, and advisors. A success message appears only after AMICOR’s lead store accepts the request. Do not submit medical records or other sensitive health information.', 'Tell us your goal and the outcome you need. For a project quote, include the deadline, approximate volume, and preferred deliverable. Do not submit medical records, passwords, or other sensitive information.').replace('Privacy Policy</a> draft', 'Privacy Policy</a>')
        if p['filename'] == 'resources/index.html':
            p['html'] = p['html'].replace('<h1>Public information only.</h1>', '<h1>Explore AMICOR resources.</h1>').replace('These links stay on the AMICOR public website. They are not internal admin tools.', 'Review our company profile, sample deliverables, product information, and policies.').replace('<article class="card"><h3>Technologies</h3>', '<article class="card"><h3>Company Profile</h3><p>Capabilities, delivery approach, and contact details.</p><a class="card-link" href="/company-profile/">View profile</a></article><article class="card"><h3>Sample Deliverables</h3><p>Fictional research, CRM, and task-register examples.</p><a class="card-link" href="/samples/">View samples</a></article><article class="card"><h3>Technologies</h3>')
