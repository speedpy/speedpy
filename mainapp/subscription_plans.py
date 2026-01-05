SUBSCRIPTION_PLANS = {
    'free': {
        'name': 'Free',
    }
}

SUBSCRIPTION_PLANS_CHOICES = [(plan_key, plan_object.get('name')) for plan_key, plan_object in SUBSCRIPTION_PLANS.items()]