from decimal import Decimal

from django.contrib import messages
from django.db.models import Q
from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView

from demoapp.forms import ProductForm
from demoapp.models import Product


DEMO_PRODUCTS = [
    {
        "name": "API Usage Pack",
        "sku": "SP-API-001",
        "category": Product.Category.SOFTWARE,
        "status": Product.Status.ACTIVE,
        "price": Decimal("49.00"),
        "inventory": 32,
        "description": "A metered add-on for teams that need extra API capacity.",
    },
    {
        "name": "Priority Support",
        "sku": "SP-SVC-002",
        "category": Product.Category.SERVICES,
        "status": Product.Status.ACTIVE,
        "price": Decimal("199.00"),
        "inventory": 12,
        "description": "Direct support coverage for launch week and production incidents.",
    },
    {
        "name": "Analytics Module",
        "sku": "SP-SW-003",
        "category": Product.Category.SOFTWARE,
        "status": Product.Status.DRAFT,
        "price": Decimal("89.00"),
        "inventory": 0,
        "description": "Dashboard reporting for product, billing, and team usage.",
    },
    {
        "name": "Onboarding Workshop",
        "sku": "SP-SVC-004",
        "category": Product.Category.SERVICES,
        "status": Product.Status.ACTIVE,
        "price": Decimal("499.00"),
        "inventory": 6,
        "description": "A guided setup session for the first production deployment.",
    },
    {
        "name": "Edge Device Kit",
        "sku": "SP-HW-005",
        "category": Product.Category.HARDWARE,
        "status": Product.Status.ARCHIVED,
        "price": Decimal("149.00"),
        "inventory": 3,
        "description": "A retired hardware bundle kept here to demonstrate archived rows.",
    },
]


class ProductListView(ListView):
    model = Product
    template_name = "demoapp/product_list.html"
    context_object_name = "products"
    paginate_by = 10

    def get_queryset(self):
        queryset = Product.objects.all()
        query = self.request.GET.get("q", "").strip()
        category = self.request.GET.get("category", "")
        status = self.request.GET.get("status", "")

        if query:
            queryset = queryset.filter(Q(name__icontains=query) | Q(sku__icontains=query))
        if category:
            queryset = queryset.filter(category=category)
        if status:
            queryset = queryset.filter(status=status)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = Product.Category.choices
        context["statuses"] = Product.Status.choices
        context["total_products"] = Product.objects.count()
        context["active_products"] = Product.objects.filter(status=Product.Status.ACTIVE).count()
        context["draft_products"] = Product.objects.filter(status=Product.Status.DRAFT).count()
        context["can_populate_demo_products"] = context["total_products"] == 0
        params = self.request.GET.copy()
        params.pop("page", None)
        context["query_string"] = params.urlencode()
        return context


class ProductPopulateDemoView(View):
    def post(self, request, *args, **kwargs):
        if Product.objects.exists():
            messages.info(request, "Demo products already exist.")
            return redirect("demo_product_list")

        Product.objects.bulk_create(Product(**product) for product in DEMO_PRODUCTS)
        messages.success(request, "Demo products generated.")
        return redirect("demo_product_list")


class ProductCreateView(CreateView):
    model = Product
    form_class = ProductForm
    template_name = "demoapp/product_form.html"

    def form_valid(self, form):
        messages.success(self.request, "Product created.")
        return super().form_valid(form)


class ProductDetailView(DetailView):
    model = Product
    template_name = "demoapp/product_detail.html"
    context_object_name = "product"


class ProductDeleteView(DeleteView):
    model = Product
    template_name = "demoapp/product_confirm_delete.html"
    context_object_name = "product"
    success_url = reverse_lazy("demo_product_list")

    def form_valid(self, form):
        messages.success(self.request, "Product deleted.")
        return super().form_valid(form)
