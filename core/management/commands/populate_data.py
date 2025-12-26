import random
from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from core.models import Negocio
from inventario.models import Producto, MovimientoInventario
from ventas.models import Venta, VentaItem
from pedidos.models import Pedido, PedidoItem, Cliente

User = get_user_model()

class Command(BaseCommand):
    help = 'Poblar base de datos con datos de prueba realistas (Ventas y Pedidos)'

    def add_arguments(self, parser):
        parser.add_argument('--ventas', type=int, default=50, help='Cantidad de ventas a crear')
        parser.add_argument('--pedidos', type=int, default=20, help='Cantidad de pedidos a crear')
        parser.add_argument('--days', type=int, default=30, help='Rango de días hacia atrás')

    def handle(self, *args, **options):
        cant_ventas = options['ventas']
        cant_pedidos = options['pedidos']
        dias_atras = options['days']

        usuario = User.objects.first()
        if not usuario:
            self.stdout.write(self.style.ERROR("No hay usuarios en el sistema. Crea un superusuario primero."))
            return

        try:
            negocio = usuario.perfilusuario.negocio
        except:
            negocio = Negocio.objects.first()
            if not negocio:
                 # Crear negocio dummy si no existe
                negocio = Negocio.objects.create(nombre="Negocio Demo", direccion="Calle Falsa 123")
                self.stdout.write(self.style.WARNING("Se creó un Negocio Demo."))

        productos = list(Producto.objects.filter(activo=True))
        if not productos:
            self.stdout.write(self.style.ERROR("No hay productos activos. Crea productos primero."))
            return

        # Poblar Clientes si hay pocos
        if Cliente.objects.count() < 5:
            self.crear_clientes_dummy(negocio)

        clientes = list(Cliente.objects.filter(negocio=negocio))

        self.stdout.write(f"Generando {cant_ventas} ventas en los últimos {dias_atras} días...")
        self.crear_ventas(cant_ventas, dias_atras, negocio, productos)

        self.stdout.write(f"Generando {cant_pedidos} pedidos en los últimos {dias_atras} días...")
        self.crear_pedidos(cant_pedidos, dias_atras, negocio, productos, clientes)

        self.stdout.write(self.style.SUCCESS("¡Datos generados correctamente!"))

    def crear_clientes_dummy(self, negocio):
        nombres = ["Juan Perez", "Maria Gonzalez", "Pedro Soto", "Ana Lopez", "Carlos Diaz"]
        for nombre in nombres:
            Cliente.objects.get_or_create(
                negocio=negocio,
                nombre=nombre,
                defaults={'rut': f"{random.randint(10,20)}.{random.randint(100,999)}.{random.randint(100,999)}-K"}
            )

    def random_date(self, days_ago):
        end = timezone.now()
        start = end - timedelta(days=days_ago)
        return start + (end - start) * random.random()

    def crear_ventas(self, n, days, negocio, productos):
        medios = [c[0] for c in Venta.MEDIO_PAGO_CHOICES]
        
        for _ in range(n):
            fecha = self.random_date(days)
            venta = Venta.objects.create(
                negocio=negocio,
                medio_pago=random.choice(medios),
                doc_tipo=Venta.DOC_BOLETA,
                fecha=fecha, # Se sobreescribirá si auto_now_add=True, ojo. 
                # Django auto_now_add ignora el valor pasado en create. 
                # Tendremos que actualizarlo después.
                estado=Venta.EST_CERRADA,
                monto_total=0
            )
            # Hack para forzar fecha pasada con auto_now_add
            Venta.objects.filter(pk=venta.pk).update(fecha=fecha)

            total = 0
            num_items = random.randint(1, 5)
            prods_venta = random.sample(productos, min(len(productos), num_items))

            for p in prods_venta:
                cantidad = random.randint(1, 3)
                precio = p.precio or 1000
                subtotal = cantidad * precio
                VentaItem.objects.create(
                    venta=venta,
                    producto=p,
                    cantidad=cantidad,
                    precio_unit=precio,
                    subtotal=subtotal
                )
                total += subtotal
                
                # Descontar stock (opcional, para realismo en reportes de stock)
                MovimientoInventario.objects.create(
                    producto=p,
                    tipo=MovimientoInventario.TIPO_VENTA,
                    cantidad=cantidad,
                    fecha=fecha,
                    venta_item=VentaItem.objects.last(), # Vinculación
                    usuario=None
                )
                # Hack fecha movimiento
                MovimientoInventario.objects.filter(pk=MovimientoInventario.objects.last().pk).update(fecha=fecha)

            venta.monto_total = total
            venta.save()

    def crear_pedidos(self, n, days, negocio, productos, clientes):
        estados_prep = [c[0] for c in Pedido.ESTADO_PREPARACION_CHOICES]
        estados_pago = [c[0] for c in Pedido.ESTADO_PAGO_CHOICES]
        formas = [c[0] for c in Pedido.FORMA_PAGO_CHOICES]

        for _ in range(n):
            fecha = self.random_date(days)
            cliente = random.choice(clientes) if clientes else None
            
            estado_p = random.choice(estados_prep)
            # Lógica simple: Si está retirado, está pagado.
            if estado_p == Pedido.PREP_RETIRADO:
                estado_pg = Pedido.PAGO_PAGADO
            else:
                estado_pg = random.choice(estados_pago)

            pedido = Pedido.objects.create(
                negocio=negocio,
                cliente=cliente,
                fecha=fecha,
                estado_preparacion=estado_p,
                estado_pago=estado_pg,
                forma_pago=random.choice(formas),
                total_monto=0
            )
            # Hack fecha
            Pedido.objects.filter(pk=pedido.pk).update(fecha=fecha)

            total = 0
            num_items = random.randint(1, 4)
            prods_pedido = random.sample(productos, min(len(productos), num_items))

            for p in prods_pedido:
                cantidad = random.randint(1, 5)
                precio = p.precio or 2000
                subtotal = cantidad * precio
                PedidoItem.objects.create(
                    pedido=pedido,
                    producto=p,
                    cantidad=cantidad,
                    precio_unit=precio,
                    subtotal=subtotal
                )
                total += subtotal
            
            pedido.total_monto = total
            pedido.save()
